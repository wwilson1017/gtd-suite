import { BASE } from '../../core/app';
import type { PaidConfig } from '../../paid/types';
// Todo GTD — typed API calls.
//
// Everything is RAW fetch. The web app's calls go to /api/app, where the browser's
// session cookie says which list; every one but /session also names the list this
// tab showed (X-List), and the answers that mean "not this list any more" are
// handed to the session store (session.ts). The landing, sign-in and capture pages
// make the handful of public calls at the bottom.
import { ApiError } from '../../core/api/client';
import { TODO_API_BASE } from './publicMode';
import { listChanged, pinnedListId, putAway, setCapped, signedOut } from './session';
import type {
  AgentLink,
  CaptureLink,
  EmailStatus,
  NewList,
  Session,
  SignInLink,
  Todo,
  TodoArea,
  TodoFilters,
  TodoProject,
  TodoStatus,
} from './types';

const SESSION_URL = `${TODO_API_BASE}/session`;
/** How the server's refusal starts when an unconfirmed list is at its cap (service._check_cap). */
const CAP_REFUSAL = 'This list holds ';

/** Path relative to the app's API root (e.g. '/todos', '/today', '/projects/3'). */
export function todoFetch<T = unknown>(
  sub: string,
  options: RequestInit = {},
  responseType: 'json' | 'blob' = 'json',
): Promise<T> {
  return rawFetch<T>(`${TODO_API_BASE}${sub}`, options, responseType);
}

function hasKey(detail: unknown, key: string): boolean {
  return typeof detail === 'object' && detail !== null && key in detail;
}

async function rawFetch<T>(url: string, options: RequestInit = {}, responseType: 'json' | 'blob' = 'json'): Promise<T> {
  const app = url.startsWith(`${TODO_API_BASE}/`);
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  const pinned = pinnedListId();
  if (app && url !== SESSION_URL && pinned !== null) headers['X-List'] = String(pinned);
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    let message = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail !== undefined) {
        detail = body.detail;
        message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // non-JSON body — keep statusText
    }
    if (app) {
      if (res.status === 401) signedOut();
      else if (res.status === 403 && hasKey(detail, 'state')) {
        putAway((detail as { state: Session['state'] }).state);
      } else if (res.status === 409 && hasKey(detail, 'list_changed')) listChanged();
      else if (res.status === 400 && typeof detail === 'string' && detail.startsWith(CAP_REFUSAL)) {
        setCapped(true);
      }
    }
    throw new ApiError(res.status, detail, `API error ${res.status}: ${message}`);
  }
  if (res.status === 204) return undefined as T;
  return responseType === 'blob' ? (res.blob() as Promise<T>) : res.json();
}

export interface TodoListParams {
  status?: TodoStatus;
  project?: string;
  context?: string;
  tag?: string;
  person?: string;
  /** An area id or name; matches the area a todo SHOWS under (its own, else its project's). */
  area?: string;
  starred?: boolean;
  due_before?: string;
  due_after?: string;
  search?: string;
  limit?: number;
  /** Keep todos waiting on a future revisit date. Record views and project-health
   *  checks only — the working lists leave them out until their day. */
  include_deferred?: boolean;
}

/** The server's largest page: `limit` is capped there (backend/router.py). */
const PAGE = 500;

/** Todos that match. An open list comes back WHOLE, however long: the server answers at
 * most 500 rows at a time, so this pages by `offset` until a short page comes back. Every
 * ordering there ends in the id, so paging an unchanged list neither skips nor repeats a
 * row. The two lists the server orders as a window (`service.list_todos`) stay ONE window
 * of `limit` rows: Done and Dropped, which grow forever and show the newest, and a search,
 * which spans them and puts the open matches first. `limit` means nothing on an open list.
 *
 * simplification: a row filed or added between two pages can be skipped or repeated until
 * the next reload; paging by a key (after the last id) is the way up. */
export async function listTodos(params: TodoListParams = {}): Promise<Todo[]> {
  if (params.status === 'done' || params.status === 'dropped' || params.search) {
    return todoPage(params);
  }
  const all: Todo[] = [];
  for (;;) {
    const page = await todoPage({ ...params, limit: PAGE, offset: all.length });
    all.push(...page);
    if (page.length < PAGE) return all;
  }
}

function todoPage(params: TodoListParams & { offset?: number }): Promise<Todo[]> {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  }
  const qs = q.toString();
  return todoFetch<{ todos: Todo[] }>(`/todos${qs ? `?${qs}` : ''}`).then((r) => r.todos);
}

export function todayTodos(): Promise<Todo[]> {
  return todoFetch<{ todos: Todo[] }>('/today').then((r) => r.todos);
}

export function createTodo(body: Partial<Todo> & { title: string; project?: string | null }): Promise<Todo> {
  return todoFetch<Todo>('/todos', { method: 'POST', body: JSON.stringify(body) });
}

export function updateTodo(id: number, fields: Record<string, unknown>): Promise<Todo> {
  return todoFetch<Todo>(`/todos/${id}`, { method: 'PUT', body: JSON.stringify(fields) });
}

/** Rename a context on every todo carrying it. 409 = `next` already exists; resend
 *  with `merge` once the user has confirmed. */
export function renameContext(
  old: string,
  next: string,
  merge = false,
): Promise<{ old: string; new: string; updated: number; merged: boolean }> {
  return todoFetch('/contexts/rename', {
    method: 'POST',
    body: JSON.stringify({ old, new: next, merge }),
  });
}

export function listProjects(status?: string): Promise<TodoProject[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  return todoFetch<{ projects: TodoProject[] }>(`/projects${qs}`).then((r) => r.projects);
}

export function createProject(body: {
  name: string;
  notes?: string;
  status?: string;
  area_id?: number | null;
  purpose?: string;
  outcome?: string;
}): Promise<TodoProject> {
  return todoFetch<TodoProject>('/projects', { method: 'POST', body: JSON.stringify(body) });
}

export function updateProject(id: number, fields: Record<string, unknown>): Promise<TodoProject> {
  return todoFetch<TodoProject>(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(fields) });
}

/** Every area, archived ones included (the Areas page restores from them). */
export function listAreas(): Promise<TodoArea[]> {
  return todoFetch<{ areas: TodoArea[] }>('/areas').then((r) => r.areas);
}

export function createArea(body: { name: string; notes?: string }): Promise<TodoArea> {
  return todoFetch<TodoArea>('/areas', { method: 'POST', body: JSON.stringify(body) });
}

export function updateArea(id: number, fields: Record<string, unknown>): Promise<TodoArea> {
  return todoFetch<TodoArea>(`/areas/${id}`, { method: 'PUT', body: JSON.stringify(fields) });
}

export function getFilters(): Promise<TodoFilters> {
  return todoFetch<TodoFilters>('/filters');
}

/** Whether a weekly review is due, and how many of the list's calendar days ago the last
 *  one was (null: never). One stamp, shared with the agents' weekly review. */
export interface ReviewStatus {
  review_due: boolean;
  days_since_review: number | null;
}

export function getReviewStatus(): Promise<ReviewStatus> {
  return todoFetch<ReviewStatus>('/review');
}

export function markReviewDone(): Promise<ReviewStatus> {
  return todoFetch<ReviewStatus>('/review/done', { method: 'POST' });
}

// ── Links, name, time zone ──────────────────────────────────────────────────

export function getCaptureLink(): Promise<CaptureLink> {
  return todoFetch<CaptureLink>('/capture-link');
}

export function regenerateCaptureLink(): Promise<CaptureLink> {
  return todoFetch<CaptureLink>('/capture-link/rotate', { method: 'POST' });
}

export function getAgentLink(): Promise<AgentLink> {
  return todoFetch<AgentLink>('/agent-link');
}

/** A new agent link. Signed-in browsers are untouched; connected AI tools must be re-added. */
export function regenerateAgentLink(): Promise<AgentLink> {
  return todoFetch<AgentLink>('/agent-link/rotate', { method: 'POST' });
}

/** '' clears the name. It is read back with the filters payload. */
export function setName(name: string): Promise<string> {
  return todoFetch<{ name: string }>('/name', { method: 'PUT', body: JSON.stringify({ name }) }).then((r) => r.name);
}

export function setTz(tz: string): Promise<string> {
  return todoFetch<{ tz: string }>('/tz', { method: 'PUT', body: JSON.stringify({ tz }) }).then((r) => r.tz);
}

// ── This browser's account ──────────────────────────────────────────────────

/** The app's first call (session.ts bootstrap). Needs no X-List. */
export function getSession(): Promise<Session> {
  return rawFetch<Session>(SESSION_URL);
}

/** Save the list's email; '' clears it. A new address (or the same unconfirmed one
 *  again: "Send again") is mailed a confirmation link, at most once per address per
 *  15 minutes — `sent` says whether one went. */
export function setEmail(email: string): Promise<EmailStatus> {
  return todoFetch<EmailStatus>('/email', { method: 'PUT', body: JSON.stringify({ email }) });
}

/** Bring an archived list back (PutAwayPage). A removed one is refused: it comes
 *  back only by confirming an email. */
export function restoreList(): Promise<{ state: Session['state'] }> {
  return todoFetch<{ state: Session['state'] }>('/restore', { method: 'POST' });
}

/** A one-hour, single-use link (and so a QR code) that signs in another device —
 *  or, with `app`, this account in another app of the suite (on that app's address). */
export function createSignInLink(app?: string): Promise<SignInLink> {
  const q = app ? `?app=${encodeURIComponent(app)}` : '';
  return todoFetch<SignInLink>(`/signin-link${q}`, { method: 'POST' });
}

/** Turn an app on or off for the account; the answer is the apps now on. */
export function setApp(key: string, on: boolean): Promise<{ apps: string[] }> {
  return todoFetch<{ apps: string[] }>(`/apps/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify({ on }),
  });
}

/** Sign this browser out. The server leaves the cookie; it simply stops working. */
export function signOut(): Promise<void> {
  return todoFetch('/signout', { method: 'POST' }).then(() => undefined);
}

/** Sign every browser out of this list, this one included. */
export function signOutEverywhere(): Promise<void> {
  return todoFetch('/signout-all', { method: 'POST' }).then(() => undefined);
}

// ── Public ──────────────────────────────────────────────────────────────────

export interface AppConfig extends PaidConfig {
  /** False when the server cannot send mail — the email sign-in hides itself. */
  mail: boolean;
  /** True on a hosted server (anyone may create a list); false on a one-list server. */
  open_signup: boolean;
  /** A one-list server whose list already exists: there is nothing left to create. */
  claimed: boolean;
  /** The operator has set a reset code, so the landing page may offer "Reset access". */
  reset: boolean;
  /** This browser is signed in to a list. */
  signed_in: boolean;
  /** This page's app (backend/apps.py), and every app with an address: the way across. */
  app: string;
  apps: Record<string, { title: string; url: string }>;
  /** The host Simple Sites hands its addresses out on, when not its own ("" then). */
  sites_short_host?: string;
}

export function getConfig(): Promise<AppConfig> {
  return rawFetch<AppConfig>(`${BASE}/api/config`);
}

/** Make a list and sign this browser in to it (the cookie is set by the answer). */
export function createList(tz: string, name = '', connect?: string): Promise<NewList> {
  return rawFetch<NewList>(`${BASE}/api/lists`, {
    method: 'POST',
    body: JSON.stringify({ tz, name, ...(connect ? { connect } : {}) }),
  });
}

/** One-list servers: every way in replaced, for whoever holds the operator's reset
 *  code — and this browser signed in. */
export function resetAccess(code: string): Promise<void> {
  return rawFetch(`${BASE}/api/reset`, { method: 'POST', body: JSON.stringify({ code }) }).then(() => undefined);
}

/** Always answers the same way, whether or not any list has that address. */
export function requestSignIn(email: string): Promise<void> {
  return rawFetch(`${BASE}/api/signin`, { method: 'POST', body: JSON.stringify({ email }) }).then(() => undefined);
}

/** Redeem a sign-in link: this browser is signed in to its list. */
export function redeemSignIn(token: string): Promise<{ verified: boolean }> {
  return rawFetch<{ verified: boolean }>(`${BASE}/api/signin/${encodeURIComponent(token)}`, {
    method: 'POST',
  });
}
