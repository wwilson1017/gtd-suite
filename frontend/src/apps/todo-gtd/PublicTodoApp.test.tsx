// @vitest-environment jsdom
//
// The boot path, end to end: `Root` is the exact component `main.tsx` renders, and it
// decides from the address alone which surface to mount. /app must reach the todo app
// on its own router basename (a lost basename is a blank page, or links that leave the
// app), and only after the session call has named the list; any other address must NOT
// mount the todo app.
//
// The network is a stubbed `fetch`, so the real api.ts and session.ts run: what the
// server is asked, in what order and with which headers, is what these tests pin.
//
// Every branch in Root is lazy, so a boot has to be settled (see `settle`) before the DOM
// reflects it.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stubNavigation } from './stubNavigation';

const LIST_ID = 7;
const SESSION = {
  list_id: LIST_ID,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: false,
  caps: { todos: 20000, projects: 1000, areas: 100 },
  apps: ['todo'],
};
const FILTERS = { contexts: [], tags: [], people: [], areas: [], status_counts: {}, tz: 'UTC', name: '' };

type Answer = { status: number; body: unknown };

/** The server: what each path answers, unless a test overrides it. */
function answer(path: string): Answer {
  if (path === '/api/app/session') return { status: 200, body: SESSION };
  if (path === '/api/config') {
    return { status: 200, body: { mail: false, open_signup: true, claimed: false, reset: false, signed_in: false } };
  }
  if (path.startsWith('/api/app/todos') || path === '/api/app/today') return { status: 200, body: { todos: [] } };
  if (path.startsWith('/api/app/projects')) return { status: 200, body: { projects: [] } };
  if (path === '/api/app/areas') return { status: 200, body: { areas: [] } };
  if (path === '/api/app/filters') return { status: 200, body: FILTERS };
  return { status: 404, body: { detail: 'Not found' } };
}

let overrides: Record<string, Answer> = {};
let fetchMock: ReturnType<typeof vi.fn>;
let nav: ReturnType<typeof stubNavigation>;

/** Every request made so far: path, method, and the X-List it carried. */
function requests() {
  return fetchMock.mock.calls.map(([url, init]) => ({
    path: String(url),
    method: (init as RequestInit | undefined)?.method ?? 'GET',
    xList: ((init as RequestInit | undefined)?.headers as Record<string, string> | undefined)?.['X-List'],
  }));
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot> | null = null;

/** Put the window on a path. publicMode reads it at module load, so every test
 * re-imports Root after calling this. */
function visit(pathname: string): void {
  window.history.replaceState({}, '', pathname);
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // jsdom keeps ONE document per file, so a title set by an earlier test survives
  // into the next one — and one test asserts the title is NOT the todo app's.
  document.title = 'Todo GTD';
  overrides = {};
  fetchMock = vi.fn(async (url: string) => {
    const path = String(url).split('?')[0];
    const { status, body } = overrides[path] ?? answer(path);
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  nav = stubNavigation();
  visit('/app');
  host = document.createElement('div');
  document.body.appendChild(host);
});

afterEach(async () => {
  // Unmount, don't just detach the container: the tree holds a useTodoMeta
  // subscription, and dropping the host node runs none of its cleanups.
  if (root) {
    const r = root;
    root = null;
    await act(async () => {
      r.unmount();
    });
  }
  host.remove();
  vi.unstubAllGlobals();
  vi.resetModules();
});

/** Boot the real Root against whatever `visit()` last set up. Each call re-imports the
 * whole graph, because `publicMode` decides at module load and the session store is
 * module state.
 *
 * The render alone commits only the Suspense fallback; call `settle()` after it. */
async function bootApp(): Promise<void> {
  const { default: Root } = await import('../../Root');
  root = createRoot(host);
  await act(async () => {
    root!.render(<Root />);
  });
}

const BOOT_TIMEOUT_MS = 30_000;
/** Strictly under BOOT_TIMEOUT_MS so `settle` throws its own diagnostic — naming the marker
 *  it waited for and what was actually on screen — before vitest's generic "test timed out"
 *  preempts it. Equal budgets meant the informative error could never win the race. */
const SETTLE_TIMEOUT_MS = 20_000;

/**
 * Drive every pending React.lazy boundary on this path to a commit, then return.
 *
 * Each cycle yields a MACROTASK inside `act`, so an import needing more than a microtask
 * still resolves and React commits the retry before `act` exits; looping until an
 * observable marker appears keeps this independent of how many boundaries a path crosses.
 *
 * Do NOT "simplify" this to `await act(async () => { await vi.waitFor(...) })` — that
 * deadlocks. `act` defers the flush until its scope exits, which is the very commit
 * `waitFor` would be polling for. The loop is bounded by WALL TIME, not a cycle count.
 */
async function settle(done: string | (() => boolean), timeoutMs = SETTLE_TIMEOUT_MS): Promise<void> {
  const check = typeof done === 'string' ? () => !!host.textContent?.includes(done) : done;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (check()) return;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
  throw new Error(
    `lazy boundaries never settled on ${String(done)}; ` + `host.textContent was ${JSON.stringify(host.textContent)}`,
  );
}

describe('the boot path', () => {
  it(
    'renders the todo app on /app, after the session call has named the list',
    async () => {
      await bootApp();
      await settle('Today');

      // The regression was an EMPTY #root. Assert on real todo chrome, not just length:
      // the tab strip every todo page renders through TodoShell.
      expect(host.textContent).toContain('Inbox');
      expect(host.textContent).toContain('Today');
      expect(document.title).toBe('Todos');

      // Every in-app link goes through todoPath(); the router basename is what turns those
      // into /app/... . A bare /inbox here would mean the basename was lost and a tap
      // would leave the app.
      const hrefs = [...host.querySelectorAll('a')].map((a) => a.getAttribute('href') ?? '');
      const inApp = hrefs.filter((h) => h.startsWith('/'));
      expect(inApp.length).toBeGreaterThan(0);
      expect(inApp.every((h) => h === '/app' || h.startsWith('/app/'))).toBe(true);

      // The session call went first and alone, with no X-List; every other app request
      // names the list it pinned.
      const app = requests().filter((r) => r.path.startsWith('/api/app/'));
      expect(app[0]).toEqual({ path: '/api/app/session', method: 'GET', xList: undefined });
      expect(app.length).toBeGreaterThan(1);
      expect(app.slice(1).every((r) => r.xList === String(LIST_ID))).toBe(true);
    },
    BOOT_TIMEOUT_MS,
  );

  // The basename exists so a sub-path resolves to its own page. Without this case the
  // suite would stay green through a basename regression that sent every deep link and
  // every reload to Today via PublicTodoApp's `*` → <Navigate to="/"> catch-all —
  // presenting as "the installed app always forgets which tab I was on", which nobody
  // reports as a router bug. Reload-on-a-sub-path is the dominant PWA interaction.
  it(
    'resolves a deep link to its own page, not the catch-all',
    async () => {
      visit('/app/inbox');
      await bootApp();
      await settle('Inbox zero');

      // Only InboxPage renders this empty state, and the stubbed server returns no todos,
      // so it is a page identity that does not depend on styling or on fixture data.
      expect(host.textContent).toContain('Inbox zero');
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'sends a signed-out browser home, and asks for nothing else first',
    async () => {
      overrides['/api/app/session'] = { status: 401, body: { detail: 'Not signed in' } };
      await bootApp();
      await settle(() => nav.replace.mock.calls.length > 0);

      expect(nav.replace).toHaveBeenCalledWith('/');
      expect(
        requests()
          .filter((r) => r.path.startsWith('/api/app/'))
          .map((r) => r.path),
      ).toEqual(['/api/app/session']);
      expect(host.textContent).not.toContain('Inbox');
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'reloads instead of carrying on when the browser is now in another list',
    async () => {
      // Another tab signed this browser in to another list: the next request names the
      // list this tab pinned, and the server refuses it.
      overrides['/api/app/today'] = { status: 409, body: { detail: { list_changed: true } } };
      await bootApp();
      await settle(() => nav.reload.mock.calls.length > 0);

      expect(nav.reload).toHaveBeenCalledTimes(1);
      expect(nav.replace).not.toHaveBeenCalled();
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'sends the browser home when a later call finds the session gone',
    async () => {
      // The session call answered, then this session was signed out (here, or from another
      // browser): the next request is refused, and the app leaves instead of showing a list.
      overrides['/api/app/today'] = { status: 401, body: { detail: 'Not signed in' } };
      await bootApp();
      await settle(() => nav.replace.mock.calls.length > 0);

      expect(nav.replace).toHaveBeenCalledWith('/');
      expect(nav.reload).not.toHaveBeenCalled();
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'shows only the put-away page for a list the session says is put away',
    async () => {
      overrides['/api/app/session'] = { status: 200, body: { ...SESSION, state: 'archived' } };
      await bootApp();
      await settle('Bring it back');

      expect(host.textContent).toContain('put away after 60 days without use');
      expect(host.textContent).not.toContain('Inbox');
      // The page loads nothing of the list's: the session call is the only app request.
      expect(
        requests()
          .filter((r) => r.path.startsWith('/api/app/'))
          .map((r) => r.path),
      ).toEqual(['/api/app/session']);
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'switches to the put-away page when a later call finds the list put away',
    async () => {
      overrides['/api/app/today'] = { status: 403, body: { detail: { state: 'removed' } } };
      await bootApp();
      await settle('Put away for good');

      expect(host.textContent).not.toContain('Inbox');
      expect(nav.reload).not.toHaveBeenCalled();
      expect(nav.replace).not.toHaveBeenCalled();
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'shows only the turn-on page when the account has this app off, and turns it on',
    async () => {
      overrides['/api/app/session'] = { status: 200, body: { ...SESSION, apps: ['projects'] } };
      overrides['/api/app/apps/todo'] = { status: 200, body: { apps: ['todo', 'projects'] } };
      overrides['/api/config'] = {
        status: 200,
        body: {
          ...answer('/api/config').body!,
          app: 'todo',
          apps: {
            todo: { title: 'Todo GTD', url: 'https://main.example' },
            projects: { title: 'Projects GTD', url: 'https://main.example/projects' },
          },
        },
      };
      await bootApp();
      await settle('Turn on Todo GTD');
      expect(host.textContent).not.toContain('Inbox');
      // The app bar stays, so a tab that led to an app that is off is not a dead end.
      const tabs = [...host.querySelectorAll('nav[aria-label="Apps"] > *')];
      expect(tabs.map((t) => t.textContent)).toEqual(['Todo', 'Projects']);
      expect(tabs[1].getAttribute('href')).toBe('https://main.example/projects/app#from=todo.7');
      expect(requests().some((r) => r.path === '/api/app/today')).toBe(false);

      const button = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Turn on Todo GTD')!;
      await act(async () => {
        button.click();
      });
      await settle('Today');
      const put = requests().find((r) => r.path === '/api/app/apps/todo')!;
      expect(put.method).toBe('PUT');
      expect(put.xList).toBe(String(LIST_ID));
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'says so when the server cannot be reached',
    async () => {
      overrides['/api/app/session'] = { status: 503, body: { detail: 'down' } };
      await bootApp();
      await settle('Could not reach the server');
      expect(host.textContent).not.toContain('Inbox');
    },
    BOOT_TIMEOUT_MS,
  );

  // The other half of the same switch: `isTodoPublicMode` decides whether the todo
  // app mounts at all. A condition that went true for ordinary traffic would put a
  // (broken) todo list where the landing page belongs.
  it(
    'serves the landing page, not the todo app, at the root',
    async () => {
      visit('/');
      await bootApp();
      await settle('Start your list');

      expect(host.textContent).toContain('Start your list');
      // The landing page talks about the Inbox too; the shell's search box is what
      // only the real app renders.
      expect(host.querySelector('[role="search"]')).toBeNull();
      expect(host.textContent).toContain('Get things done with your AI.');
      expect(document.title).not.toBe('Todos');
      expect(requests().map((r) => r.path)).toEqual(['/api/config']);
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'serves the capture page at /c/{token}',
    async () => {
      visit('/c/CAPTURETOKEN');
      await bootApp();
      await settle('straight to your inbox');

      expect(host.querySelector('textarea')).not.toBeNull();
    },
    BOOT_TIMEOUT_MS,
  );

  it(
    'serves the sign-in page at /signin/{token} without redeeming on load',
    async () => {
      visit('/signin/SIGNINTOKEN');
      await bootApp();
      await settle('Open my list on this device');

      // Only the button's POST may redeem: a mail scanner loading the page must change nothing.
      expect(requests().filter((r) => r.method !== 'GET')).toEqual([]);
      expect(requests().some((r) => r.path.includes('SIGNINTOKEN'))).toBe(false);
    },
    BOOT_TIMEOUT_MS,
  );
});
