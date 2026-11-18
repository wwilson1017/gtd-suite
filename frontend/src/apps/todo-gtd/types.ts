import type { Plan } from '../../paid/types';

// Todo GTD — shared types (mirrors backend/common.py)

export type TodoStatus = 'inbox' | 'next_action' | 'waiting_for' | 'delegated' | 'someday_maybe' | 'done' | 'dropped';

export type TodoProjectStatus = 'active' | 'someday' | 'completed' | 'dropped';

export interface Todo {
  id: number;
  title: string;
  notes: string;
  project_id: number | null;
  project_name: string | null;
  /** The todo's OWN area. Unset means "its project's area, if any". */
  area_id?: number | null;
  /** The area it shows under: its own, else its project's. `area_name` names this one. */
  effective_area_id?: number | null;
  area_name?: string | null;
  context: string;
  tags: string[];
  /** Who it involves. Same shape and caps as `tags`. */
  people?: string[];
  status: TodoStatus;
  star: boolean;
  due_date: string | null; // YYYY-MM-DD
  /** YYYY-MM-DD: the server keeps the item off the working lists until this day; from
   *  then on it shows as usual and on Today. Nothing moves by itself. */
  revisit_on?: string | null;
  repeat: string; // '' | daily | weekdays | weekly | monthly | yearly | every:N
  /** Repeating todos only: star the next occurrence when it comes due today. */
  auto_star_on_due: boolean;
  /** Which surface CREATED the row: 'ui' | 'capture' | 'agent'. Never changes. */
  source: string;
  /** The AI tool's self-reported name on agent-created rows, when known. Untrusted text. */
  source_client?: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TodoArea {
  id: number;
  name: string;
  notes: string;
  status: 'active' | 'dropped';
  created_at: string;
  updated_at: string;
}

export interface TodoProject {
  id: number;
  name: string;
  notes: string;
  /** Why it matters / what done looks like. */
  purpose?: string;
  outcome?: string;
  area_id?: number | null;
  area_name?: string | null;
  status: TodoProjectStatus;
  open_count: number;
  created_at: string;
  updated_at: string;
}

/** A Todo project's home in Projects GTD (backend/project_links.py), each side as it is now. */
export interface ProjectLink {
  project_id: number;
  project_name: string;
  project_status: TodoProjectStatus;
  /** The Projects GTD project (a board there). */
  board_id: number;
  board_name: string;
  board_status: 'active' | 'archived';
  created_at: string;
}

export interface TodoFilters {
  contexts: string[];
  tags: string[];
  /** Everyone named on any todo — the people input's suggestions and the people facet. */
  people?: string[];
  /** The ACTIVE areas — what the area pickers offer. */
  areas?: { id: number; name: string }[];
  status_counts: Record<TodoStatus, number>;
  /** The list's IANA time zone — "today" is computed in it, never in the browser's. */
  tz?: string;
  /** The list's optional name; '' when it has none. */
  name?: string;
}

/** A link the web app can always show again. */
export interface CaptureLink {
  url: string;
  token: string;
}
export type AgentLink = CaptureLink;

/** What creating a list answers. The browser is signed in by a cookie the page
 *  never sees; the agent link is shown again on Your AI. */
export interface NewList {
  agent_token: string;
  agent_url: string;
  tz: string;
  name: string;
}

/** GET /api/app/session — the app's first call: which list this browser is in. */
export interface Session {
  brains?: import('./brainSelection').BrainSummary[];
  list_id: number;
  /** The account's random number (1234-5678): what a person says to name their account. */
  account_no?: string;
  /** A hosted list with no confirmed email is put away after 60 days without use
   *  ('archived': one button brings it back) and for good after 180 ('removed': a
   *  confirmed email brings it back). Anything but 'active' shows PutAwayPage. */
  state: 'active' | 'archived' | 'removed';
  email: string | null;
  /** The email is confirmed (a link mailed to it was opened): the list is kept, with larger caps. */
  verified: boolean;
  /** A hosted (open-signup) server rather than a one-list self-host. */
  hosted: boolean;
  /** The server can send mail (sign-in and confirmation links). */
  mail: boolean;
  /** How many of each this list can hold now (counting archived ones). */
  caps: {
    todos: number;
    projects: number;
    areas: number;
    brains?: number;
    links?: number;
    upsell?: boolean;
    storage?: number;
    storage_used?: number;
  };
  /** The apps (backend/apps.py keys) turned on for the account: the agent link offers
   *  only these, and an app that is off shows AppOff on its own address. */
  apps: string[];
  /** The AI tools that have called the agent link, the latest caller first (Your AI,
   *  the pinned Connect card). Empty until one has. */
  ai_tools?: AiTool[];
  /** The account’s plan, as last synced from the payment service. */
  plan?: Plan;
}

/** An AI tool that has called the account's agent link. */
export interface AiTool {
  /** What the tool calls itself: its own claim, shown as text. '' when it gave no name. */
  name: string;
  /** The day it last called, YYYY-MM-DD in the list's time zone, and how many calendar
   *  days ago that was. Both null for a tool known only from what it wrote earlier. */
  last_used: string | null;
  days_ago: number | null;
}

/** What saving the list's email answers. */
export interface EmailStatus {
  email: string | null;
  verified: boolean;
  /** Whether a mail went out. */
  sent: boolean;
  /** The list's caps after this change; they follow verification. */
  caps: Session['caps'];
}

/** A one-hour, single-use sign-in link (Connect → Sign in on another device). */
export interface SignInLink {
  url: string;
  expires_at: string;
}
