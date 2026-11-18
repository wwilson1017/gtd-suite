// Projects GTD — the shapes backend/boards.py answers with.
import type { TodoProjectStatus } from '../todo-gtd/types';

export interface Label {
  id: number;
  name: string;
  color: string;
}

export type ColumnKind = 'triage' | 'not_now' | 'column' | 'done';

export interface Card {
  id: number;
  board_id: number;
  board_name: string;
  column_id: number;
  column_name: string;
  column_kind?: ColumnKind;
  title: string;
  notes: string;
  due_date: string | null;
  starts_on?: string | null;
  assignees?: { id: number; name: string; kind: 'me' | 'person' | 'ai'; color: string }[];
  labels?: Label[];
  cover?: string;
  /** In its column's On Hold section. */
  on_hold?: boolean;
  /** In Done. */
  completed?: boolean;
  steps_count?: number;
  steps_done?: number;
  comments_count?: number;
  /** Finishing it adds the next (recordings.REPEATS). */
  repeat?: string | null;
  /** A card template: "Use this template" makes a new card like it. */
  template?: boolean;
  position: number;
  status: 'active' | 'archived';
  source: 'ui' | 'agent';
  source_client: string | null;
  /** Goes up on every change; an edit sent with an older one is refused (409). */
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Column {
  id: number;
  board_id: number;
  name: string;
  position: number;
  /** Basecamp's fixed columns (Triage, Not now, Done) and the work columns between. */
  kind?: ColumnKind;
  /** Done: finished cards, newest on top. */
  done: boolean;
  color?: string;
  has_on_hold?: boolean;
  /** Trello's soft list limit: over it the column warns. */
  card_limit?: number | null;
  description?: string;
  cards: Card[];
}

export interface Board {
  id: number;
  name: string;
  notes: string;
  status: 'active' | 'archived';
  updated_at: string;
  columns: Column[];
  archived_cards: number;
  labels?: Label[];
  template?: number;
  /** One of the sample projects (backend/samples.py). */
  sample?: boolean;
  /** Basecamp 5's wormholes: columns of other projects a card dropped here goes to. */
  wormholes?: Wormhole[];
}

export interface Wormhole {
  id: number;
  column_id: number;
  column_name: string;
  project_id: number;
  project_name: string;
}

export interface BoardSummary {
  id: number;
  name: string;
  notes: string;
  status: 'active' | 'archived';
  updated_at: string;
  cards: number;
  columns: { id: number; name: string; cards: number }[];
  /** A project template: new projects can start from it. */
  template?: number;
  /** One of the sample projects (backend/samples.py). */
  sample?: boolean;
}

/** Where a card goes in its column: 'top', 'bottom' or a 0-based index. */
export type Position = 'top' | 'bottom' | number;

// ── Projects as Basecamp (backend/recordings.py, people.py) ───────────────────

export interface Person {
  id: number;
  name: string;
  /** 'me' is the account's person; 'ai' an AI tool that has written; 'person' one added by name. */
  kind: 'me' | 'person' | 'ai';
  color: string;
  title?: string;
  status?: 'active' | 'archived';
}

export interface Boost {
  id: number;
  content: string;
  booster: Person | null;
  created_at: string;
}

export type ItemType =
  | 'message'
  | 'todolist'
  | 'todolist_group'
  | 'todo'
  | 'step'
  | 'comment'
  | 'vault'
  | 'document'
  | 'link'
  | 'schedule_entry'
  | 'question'
  | 'answer'
  | 'needle'
  | 'hill_update'
  | 'chat_line'
  | 'door'
  | 'wormhole';
export type ItemStatus = 'active' | 'archived' | 'trashed' | 'drafted';

/** One recording: a message, a to-do list, a group, a to-do, a subtask or a comment. */
export interface Item {
  id: number;
  board_id: number;
  board_name: string;
  parent_id: number | null;
  card_id: number | null;
  type: ItemType;
  title: string;
  body: string;
  status: ItemStatus;
  position: number;
  category: string;
  color: string;
  starts_on: string | null;
  due_on: string | null;
  completed: boolean;
  completed_at: string | null;
  completer: Person | null;
  assignees: Person[];
  creator: Person | null;
  source: 'ui' | 'agent';
  source_client: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  comments_count: number;
  pinned_at?: string | null;
  /** To-do lists and groups: how many of their to-dos are done, of how many. */
  completed_count?: number;
  todos_count?: number;
  boosts?: Boost[];
  bookmarked?: boolean;
  /** A group, inside its list's page: its open and its completed to-dos. */
  todos?: Item[];
  completed_todos?: Item[];
  // Docs & Files, Calendar, Check-ins (the type's own fields, kept in its data).
  url?: string;
  items_count?: number;
  starts_at?: string | null;
  ends_at?: string | null;
  all_day?: boolean;
  highlighted?: boolean;
  repeat?: string | null;
  repeat_until?: string | null;
  frequency?: string;
  days?: number[];
  time?: string;
  paused?: boolean;
  group_on?: string;
  // The Needle, a Hill Chart update, the Spotlight.
  needle?: Needle;
  lists?: HillList[];
  spotlight?: boolean;
  post_at?: string | null;
}

export type Needle = 'on_track' | 'some_risk' | 'concerned';
/** A to-do list on the Hill Chart: 0 the bottom left, 50 the top, 100 done. */
export interface HillList {
  id: number;
  title: string;
  color: string;
  hill: number;
}
export interface HillChart {
  lists: HillList[];
  updates: Item[];
  updated_at: string | null;
  stale: boolean;
}

/** One day an event happens on (`on` to `until`), from a calendar read. */
export type Occurrence = Item & { on: string; until: string };
export interface DueOnCalendar {
  kind: 'todo' | 'step' | 'card';
  id: number;
  card_id: number | null;
  title: string;
  on: string;
  board_id: number;
  board_name: string;
  parent_id: number | null;
  assignees: { id: number; name: string; kind: 'me' | 'person' | 'ai'; color: string }[];
}
export interface CalendarRange {
  start: string;
  end: string;
  events: Occurrence[];
  due: DueOnCalendar[];
}

export interface Thread {
  recording: Item;
  ancestors: { id: number; type: ItemType; title: string }[];
  comments: Item[];
  children?: Item[];
  completed?: Item[];
}

export type Tool =
  'message_board' | 'todoset' | 'vault' | 'chat' | 'schedule' | 'questionnaire' | 'kanban_board' | 'doors';

export interface DockEntry {
  tool: Tool;
  title: string;
  enabled: boolean;
}

export interface ActivityEvent {
  id: number;
  board_id: number;
  board_name: string;
  recording_id: number | null;
  card_id: number | null;
  recording_type: ItemType | null;
  recording_title: string | null;
  recording_parent_id: number | null;
  card_title: string | null;
  /** The card's project now (it may have moved since). */
  card_board_id?: number | null;
  action: string;
  verb: string;
  detail: string;
  creator: Person | null;
  created_at: string;
}

export interface Project {
  id: number;
  name: string;
  notes: string;
  status: 'active' | 'archived';
  pinned: number;
  /** A project template (1): new projects can start from it. */
  template?: number;
  /** One of the sample projects (backend/samples.py). */
  sample?: boolean;
  folder?: string;
  starts_on: string | null;
  ends_on: string | null;
  updated_at: string;
  dock: DockEntry[];
  previews: {
    message_board?: Item[];
    todoset?: Item[];
    vault?: Item[];
    schedule?: CalendarRange;
    questionnaire?: Item[];
    kanban_board?: { id: number; name: string; cards: number; kind?: string }[];
    hill?: HillList[];
    chat?: Item[];
    doors?: Item[];
  };
  spotlight: Item[];
  needle: Item | null;
  bookmarked: boolean;
  people: Person[];
  /** The Todo project this one is the home of, when there is one (backend/project_links.py). */
  todo_project?: { id: number; name: string; status: TodoProjectStatus };
}

export interface HomeProject extends BoardSummary {
  pinned: number;
  people: Person[];
  /** The Home folder it sits in (Basecamp 5's), or '' for none. */
  folder?: string;
}

export interface Home {
  projects: HomeProject[];
  activity: ActivityEvent[];
  assignments: Item[];
}

export interface Bookmark {
  id: number;
  board_id: number | null;
  recording_id: number | null;
  card_id: number | null;
  title: string;
  recording_type: ItemType | null;
  board_name: string;
  project_id: number;
  created_at: string;
}
