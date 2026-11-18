// Projects GTD — the board API (backend/board_routes.py), through the todo app's
// fetch, which names the session's list (X-List) and handles signed-out, put-away
// and list-changed answers the same way for both apps.
import { todoFetch } from '../todo-gtd/api';
import type {
  ActivityEvent,
  Board,
  BoardSummary,
  Bookmark,
  Boost,
  Card,
  DockEntry,
  Home,
  Item,
  ItemType,
  Label,
  Person,
  Position,
  Project,
  Thread,
  CalendarRange,
  HillChart,
} from './types';

function send<T>(method: string, sub: string, body: unknown): Promise<T> {
  return todoFetch<T>(sub, { method, body: JSON.stringify(body) });
}

export function listBoards(status: 'active' | 'archived' = 'active'): Promise<BoardSummary[]> {
  return todoFetch<{ boards: BoardSummary[] }>(`/boards?status=${status}`).then((r) => r.boards);
}

/** `tools`: the ones it starts with; [] starts it empty (Basecamp 5), leaving it out keeps a card table. */
export function createBoard(name: string, notes = '', tools?: string[]): Promise<Board> {
  return send('POST', '/boards', { name, notes, ...(tools ? { tools } : {}) });
}

export function getBoard(id: number): Promise<Board> {
  return todoFetch<Board>(`/boards/${id}`);
}

export function updateBoard(
  id: number,
  fields: Partial<Pick<Board, 'name' | 'notes' | 'status'>> & {
    pinned?: boolean;
    starts_on?: string | null;
    ends_on?: string | null;
    template?: boolean;
    folder?: string;
  },
): Promise<Board> {
  return send('PUT', `/boards/${id}`, fields);
}

/** The server's page of archived cards (backend/boards.py archived_cards). */
export const ARCHIVED_PAGE = 200;

/** A board's archived cards, newest change first, from `offset`. */
export function archivedCards(boardId: number, offset = 0): Promise<Card[]> {
  return todoFetch<{ cards: Card[] }>(`/boards/${boardId}/archived?offset=${offset}`).then((r) => r.cards);
}

export function addColumn(boardId: number, name: string): Promise<Board> {
  return send('POST', `/boards/${boardId}/columns`, { name });
}

export function updateColumn(
  id: number,
  fields: {
    name?: string;
    status?: 'active' | 'archived';
    position?: Position;
    color?: string;
    has_on_hold?: boolean;
    card_limit?: number | null;
    description?: string;
  },
): Promise<Board> {
  return send('PUT', `/columns/${id}`, fields);
}

export function createCard(boardId: number, columnId: number, title: string, position?: Position): Promise<Card> {
  return send('POST', `/boards/${boardId}/cards`, {
    title,
    column_id: columnId,
    ...(position !== undefined ? { position } : {}),
  });
}

export type CardFields = Partial<
  Pick<
    Card,
    'title' | 'notes' | 'due_date' | 'status' | 'starts_on' | 'cover' | 'on_hold' | 'completed' | 'repeat' | 'template'
  >
> & { assignee_ids?: (number | string)[]; labels?: (number | string)[] };

export const moveAllCards = (columnId: number, toColumnId: number) =>
  send<Board>('POST', `/columns/${columnId}/move-cards`, { to_column_id: toColumnId });
export const archiveAllCards = (columnId: number) => send<Board>('POST', `/columns/${columnId}/archive-cards`, {});
export const sortColumn = (columnId: number, by: 'due' | 'created' | 'newest' | 'title') =>
  send<Board>('POST', `/columns/${columnId}/sort`, { by });
export const listLabels = (boardId: number) =>
  todoFetch<{ labels: Label[] }>(`/boards/${boardId}/labels`).then((r) => r.labels);
export const createLabel = (boardId: number, name: string, color = '') =>
  send<Label>('POST', `/boards/${boardId}/labels`, { name, color });
export const updateLabel = (id: number, fields: { name?: string; color?: string; status?: 'active' | 'archived' }) =>
  send<Label>('PUT', `/labels/${id}`, fields);

/** What a card's 409 says, wherever a card is written from; the writer then shows the latest. */
export const CARD_CHANGED =
  'This card changed somewhere else (your AI, or another device). Showing the latest; make your change again.';
/** The same, where the latest could not then be read: what is on screen is still the old card. */
export const CARD_CHANGED_UNREAD =
  'This card changed somewhere else (your AI, or another device). Reload the page to see the latest.';

/** With `version`, the server refuses (409) when the card changed since it was read. */
export function updateCard(id: number, fields: CardFields & { version?: number }): Promise<Card> {
  return send('PUT', `/cards/${id}`, fields);
}

export const getCard = (id: number) => todoFetch<Card>(`/cards/${id}`);

/** With `version`, the server refuses (409) when the card changed since it was read, and nothing moves. */
export function moveCard(
  id: number,
  columnId: number,
  position?: Position,
  onHold?: boolean,
  version?: number,
): Promise<Card> {
  return send('POST', `/cards/${id}/move`, {
    column_id: columnId,
    position,
    ...(onHold !== undefined ? { on_hold: onHold } : {}),
    ...(version !== undefined ? { version } : {}),
  });
}
/** To another project: to its Triage. */
export const moveCardToProject = (id: number, projectId: number) =>
  send<Card>('POST', `/cards/${id}/move`, { project_id: projectId });
/** Copy a card (or make one from a card template): its column by default, or a project's Triage. */
export const copyCard = (id: number, to: { column_id?: number; project_id?: number; title?: string } = {}) =>
  send<Card>('POST', `/cards/${id}/copy`, to);
/** Every card template in the account's open projects (Trello's "Create from template"). */
export interface CardTemplate {
  id: number;
  title: string;
  board_id: number;
  board_name: string;
}
export const cardTemplates = () => todoFetch<{ templates: CardTemplate[] }>('/card-templates').then((r) => r.templates);

// ── Projects as Basecamp (backend/project_routes.py) ─────────────────────────

export const getHome = () => todoFetch<Home>('/home');

export const listPeople = () => todoFetch<{ people: Person[] }>('/people').then((r) => r.people);
export const addPerson = (name: string, title = '') => send<Person>('POST', '/people', { name, title });
export const updatePerson = (id: number, fields: Partial<Pick<Person, 'name' | 'title' | 'color' | 'status'>>) =>
  send<Person>('PUT', `/people/${id}`, fields);

export const getProject = (id: number) => todoFetch<Project>(`/projects/${id}`);
export const setDock = (id: number, dock: DockEntry[]) =>
  send<{ dock: DockEntry[] }>('PUT', `/projects/${id}/dock`, { dock }).then((r) => r.dock);

export interface ItemFields {
  url?: string;
  ends_on?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  all_day?: boolean;
  highlighted?: boolean;
  repeat?: string | null;
  repeat_until?: string | null;
  frequency?: string;
  days?: number[];
  time?: string | null;
  paused?: boolean;
  group_on?: string;
  needle?: string;
  spotlight?: boolean;
  post_at?: string | null;
  column_id?: number;
  title?: string;
  body?: string;
  status?: Item['status'];
  category?: string;
  color?: string;
  due_on?: string | null;
  starts_on?: string | null;
  assignee_ids?: (number | string)[];
  pinned?: boolean;
}

export function listItems(
  projectId: number,
  type: ItemType,
  opts: { status?: Item['status']; parent_id?: number; sort?: 'newest' | 'activity' | 'alpha' } = {},
): Promise<Item[]> {
  const q = new URLSearchParams({ type });
  if (opts.status) q.set('status', opts.status);
  if (opts.parent_id !== undefined) q.set('parent_id', String(opts.parent_id));
  if (opts.sort) q.set('sort', opts.sort);
  return todoFetch<{ items: Item[] }>(`/projects/${projectId}/items?${q}`).then((r) => r.items);
}

export const createItem = (
  projectId: number,
  type: ItemType,
  fields: ItemFields,
  place: { parent_id?: number; card_id?: number; position?: Position } = {},
) => send<Item>('POST', `/projects/${projectId}/items`, { type, ...fields, ...place });

export const getItem = (id: number) => todoFetch<Thread>(`/items/${id}`);
/** With `version`, the server refuses (409) when the item changed since it was read. */
export const updateItem = (id: number, fields: ItemFields & { version?: number }) =>
  send<Item>('PUT', `/items/${id}`, fields);
export const completeItem = (id: number, done: boolean) => send<Item>('POST', `/items/${id}/complete`, { done });
export const moveItem = (
  id: number,
  to: { parent_id?: number; project_id?: number; position?: Position; before_id?: number },
) => send<Item>('POST', `/items/${id}/move`, to);
export const commentOn = (id: number, body: string) => send<Item>('POST', `/items/${id}/comments`, { body });
export const boostItem = (id: number, content: string) => send<Boost>('POST', `/items/${id}/boosts`, { content });

export const cardThread = (id: number) =>
  todoFetch<{ comments: Item[]; subtasks: Item[]; boosts: Boost[] }>(`/cards/${id}/thread`);
export const commentOnCard = (id: number, body: string) => send<Item>('POST', `/cards/${id}/comments`, { body });
export const boostCard = (id: number, content: string) => send<Boost>('POST', `/cards/${id}/boosts`, { content });
export const removeBoost = (id: number) => send<{ id: number }>('POST', `/boosts/${id}/remove`, {});

export const listBookmarks = () => todoFetch<{ bookmarks: Bookmark[] }>('/bookmarks').then((r) => r.bookmarks);
export const setBookmark = (target: { item_id?: number; card_id?: number; project_id?: number }, on: boolean) =>
  send<{ bookmarked: boolean }>('POST', '/bookmarks', { ...target, on });

export function getActivity(opts: { project_id?: number; person_id?: number; item_id?: number; before?: number } = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(opts)) if (v !== undefined) q.set(k, String(v));
  return todoFetch<{ events: ActivityEvent[]; next_before: number | null }>(`/activity?${q}`);
}

/** Where someone @mentioned a person lately. */
export interface Mention {
  id: number;
  type: string;
  board_id: number;
  board_name: string;
  parent_id: number | null;
  card_id: number | null;
  excerpt: string;
  creator: Person | null;
  created_at: string;
}
export const getAssignments = (personId?: number) =>
  todoFetch<{ todos: Item[]; cards: Card[]; mentions?: Mention[] }>(
    `/assignments${personId ? `?person_id=${personId}` : ''}`,
  );

export interface Todoset {
  loose: Item[];
  loose_completed: Item[];
  lists: (Item & { children: Item[]; completed_todos: Item[] })[];
}
export const getTodoset = (projectId: number, status: Item['status'] = 'active') =>
  todoFetch<Todoset>(`/projects/${projectId}/todos?status=${status}`);

// ── New for you, Up Next, My Drafts, My Boosts (backend/inbox.py) ─────────────

export interface InboxItem {
  key: string;
  recording_id: number | null;
  card_id: number | null;
  board_id: number;
  board_name: string;
  title: string;
  type: string;
  last: { verb: string; action: string; detail: string; created_at: string; creator: Person } | null;
  people: string[];
  unread_count: number;
  bubble_up_at: string | null;
  /** "Don't notify me": the item, or its whole project (project_muted), is muted. */
  muted?: boolean;
  project_muted?: boolean;
}
export interface DueItem {
  recording_id: number | null;
  card_id: number | null;
  board_id: number;
  board_name: string;
  title: string;
  due: string;
}
export interface Inbox {
  bubbled: InboxItem[];
  unread: InboxItem[];
  previous: InboxItem[];
  due: DueItem[];
  scheduled_bubble_ups: number;
  unread_count: number;
}
export type InboxTarget = { item_id?: number; card_id?: number; project_id?: number };

export const inboxTarget = (i: {
  recording_id: number | null;
  card_id: number | null;
  board_id: number;
}): InboxTarget =>
  i.recording_id ? { item_id: i.recording_id } : i.card_id ? { card_id: i.card_id } : { project_id: i.board_id };
export const getInbox = () => todoFetch<Inbox>('/inbox');
export const inboxCount = () => todoFetch<{ unread: number }>('/inbox/count').then((r) => r.unread);
export const markRead = (target: InboxTarget, read = true) =>
  send<{ read: boolean }>('POST', '/inbox/read', { ...target, read });
/** Basecamp's "Don't notify me" on an item, a card or a whole project (its bell). */
export const getMuted = (target: InboxTarget) =>
  todoFetch<{ muted: boolean }>(
    `/inbox/mute?${new URLSearchParams(Object.entries(target).map(([k, v]) => [k, String(v)]))}`,
  ).then((r) => r.muted);
export const setMuted = (target: InboxTarget, muted: boolean) =>
  send<{ muted: boolean }>('POST', '/inbox/mute', { ...target, muted });
export const markAllRead = () => send<{ read_at: string }>('POST', '/inbox/read-all', {});
export const BUBBLE_TIMES = [
  ['now', 'Now'],
  ['later_today', 'Later today'],
  ['tomorrow', 'Tomorrow'],
  ['this_weekend', 'This weekend'],
  ['next_week', 'Next week'],
] as const;
export const bubbleUp = (target: InboxTarget, when: string | null) =>
  send<{ bubble_up_at: string | null }>('POST', '/inbox/bubble-up', { ...target, when });
export type UpNextItem = (Item | Card) & { kind: 'todo' | 'card' };
export const getUpNext = () => todoFetch<{ items: UpNextItem[] }>('/up-next').then((r) => r.items);
export const setUpNext = (items: ['r' | 'c', number][]) =>
  send<{ items: UpNextItem[] }>('PUT', '/up-next', { items }).then((r) => r.items);
export const getDrafts = () => todoFetch<{ items: Item[] }>('/drafts').then((r) => r.items);
export interface MyBoost {
  id: number;
  content: string;
  booster: Person | null;
  created_at: string;
  recording_id: number | null;
  card_id: number | null;
  board_id: number;
  title: string;
  recording_type: string | null;
}
export const getMyBoosts = () => todoFetch<{ boosts: MyBoost[] }>('/my-boosts').then((r) => r.boosts);

// ── Docs & Files, Calendar, Check-ins, the Lineup (project_routes.py) ─────────

export interface Folder {
  folder_id: number | null;
  above: { id: number; title: string }[];
  items: Item[];
}
export const getFolder = (projectId: number, folderId?: number | null, sort = 'name') =>
  todoFetch<Folder>(`/projects/${projectId}/docs?sort=${sort}${folderId ? `&folder_id=${folderId}` : ''}`);
export const getCalendar = (start: string, end: string, projectId?: number, includeDue = true) =>
  todoFetch<CalendarRange>(
    `${projectId ? `/projects/${projectId}/calendar` : '/calendar'}?start=${start}&end=${end}&include_due=${includeDue}`,
  );
export const getAnswers = (questionId: number, personId?: number) =>
  todoFetch<{ days: { day: string; answers: Item[] }[] }>(
    `/items/${questionId}/answers${personId ? `?person_id=${personId}` : ''}`,
  ).then((r) => r.days);
export const getCheckinsDue = () =>
  todoFetch<{ questions: { id: number; title: string; board_id: number; board_name: string; group_on: string }[] }>(
    '/checkins/due',
  ).then((r) => r.questions);
export interface LineupProject {
  id: number;
  name: string;
  notes: string;
  starts_on: string;
  ends_on: string;
  pinned: number;
}
export const getLineup = (start: string, end: string) =>
  todoFetch<{ projects: LineupProject[] }>(`/lineup?start=${start}&end=${end}`).then((r) => r.projects);

// ── Hill Charts, the Needle, the archive; Everything, Reports, search ─────────

export const getHill = (projectId: number) => todoFetch<HillChart>(`/projects/${projectId}/hill`);
export const setHill = (projectId: number, positions: Record<string, number | null>, note: string) =>
  send<HillChart>('POST', `/projects/${projectId}/hill`, { positions, note });
export const getNeedles = (projectId: number) =>
  todoFetch<{ needles: Item[] }>(`/projects/${projectId}/needle`).then((r) => r.needles);
export interface PutAway {
  archived: Item[];
  trashed: Item[];
  cards: Card[];
}
export const getPutAway = (projectId: number) => todoFetch<PutAway>(`/projects/${projectId}/put-away`);

export type EverythingKind = 'messages' | 'docs' | 'tasks' | 'comments' | 'checkins';
export type ReportItem = Omit<Item, 'type'> & {
  type: Item['type'] | 'card';
  on_title?: string;
  on_type?: string | null;
  column_name?: string;
  due_date?: string | null;
};
export const getEverything = (kind: EverythingKind, before?: string | null, subtasks = false) =>
  todoFetch<{ items: ReportItem[]; next_before: string | null }>(
    `/everything?kind=${kind}&subtasks=${subtasks}${before ? `&before=${encodeURIComponent(before)}` : ''}`,
  );

export interface DueItem {
  kind: 'todo' | 'step' | 'card';
  id: number;
  card_id: number | null;
  title: string;
  on: string;
  days_late?: number;
  board_id: number;
  board_name: string;
  parent_id: number | null;
  assignees: Person[];
}
export const getOverdue = () =>
  todoFetch<{ today: string; count: number; groups: { label: string; items: DueItem[] }[] }>('/reports/overdue');
export const getUpcoming = (days = 14) =>
  todoFetch<{ today: string; items: DueItem[] }>(`/reports/upcoming?days=${days}`);
export const getUnassigned = () => todoFetch<{ todos: Item[]; cards: Card[] }>('/reports/unassigned');
export const getProgress = (start: string, end: string) =>
  todoFetch<{ added: ReportItem[]; completed: ReportItem[] }>(`/reports/progress?start=${start}&end=${end}`);
export const getPersonTasks = (personId: number) =>
  todoFetch<{ person: Person; todos: Item[]; cards: Card[] }>(`/reports/person/${personId}`);
export interface MissionProject {
  id: number;
  name: string;
  pinned: number;
  needle: Item | null;
  last_activity_at: string | null;
  quiet: boolean;
}
export const getMissionControl = () =>
  todoFetch<{ projects: MissionProject[] }>('/reports/mission-control').then((r) => r.projects);
export const getHilltop = () =>
  todoFetch<{ projects: (HillChart & { id: number; name: string })[] }>('/reports/hilltop').then((r) => r.projects);

export interface SearchResult {
  id: number;
  type: string;
  title: string;
  snippet: string;
  board_id: number;
  board_name: string;
  parent_id: number | null;
  card_id: number | null;
  status: string;
  creator: Person | null;
  created_at: string;
  title_match: boolean;
  column_name?: string;
}
export const search = (params: Record<string, string>) =>
  todoFetch<{ q: string; count: number; results: SearchResult[] }>(`/search?${new URLSearchParams(params)}`);

// ── Copies and templates ──────────────────────────────────────────────────────

export const copyItem = (id: number, to: { project_id?: number; parent_id?: number } = {}) =>
  send<Item>('POST', `/items/${id}/copy`, to);
export const getTemplates = () =>
  todoFetch<{ templates: { id: number; name: string; notes: string }[] }>('/templates').then((r) => r.templates);
export const startFromTemplate = (id: number, name: string, startsOn?: string) =>
  send<Board>('POST', `/templates/${id}/use`, { name, ...(startsOn ? { starts_on: startsOn } : {}) });

// ── Card Table automation (backend/automation.py) ─────────────────────────────

export type RuleKind = 'rule' | 'card_button' | 'board_button';
export interface RuleAction {
  do: string;
  column?: number;
  position?: 'top' | 'bottom';
  people?: (number | string)[];
  label?: number;
  titles?: string[];
  text?: string;
  days?: number;
  on?: boolean;
}
export interface Rule {
  id: number;
  board_id: number;
  kind: RuleKind;
  name: string;
  /** A scheduled rule (on 'scheduled') also has every ('day' | 'weekday' | 'week' | 'month'), day and time (HH:MM). */
  trigger: { on?: string; column?: number; days?: number; every?: string; day?: number; time?: string };
  actions: RuleAction[];
  status: 'active' | 'archived';
  runs: number;
  last_run_at: string | null;
  last_error: string | null;
}
export const getRules = (boardId: number, status: 'active' | 'archived' = 'active') =>
  todoFetch<{ rules: Rule[] }>(`/boards/${boardId}/rules?status=${status}`).then((r) => r.rules);
export const createRule = (
  boardId: number,
  rule: { kind: RuleKind; name: string; trigger: Rule['trigger']; actions: RuleAction[] },
) => send<Rule>('POST', `/boards/${boardId}/rules`, rule);
export const updateRule = (id: number, fields: Partial<Pick<Rule, 'name' | 'trigger' | 'actions' | 'status'>>) =>
  send<Rule>('PUT', `/rules/${id}`, fields);
export const pressRule = (id: number, cardId?: number) =>
  send<{ rule: Rule; cards: number }>('POST', `/rules/${id}/press`, cardId ? { card_id: cardId } : {});

// ── Chat (recordings.chat) ────────────────────────────────────────────────────

export interface ChatRoom {
  lines: Item[];
  latest: number;
  earlier: boolean;
}
export const getChat = (projectId: number, opts: { since?: number; before?: number } = {}) =>
  todoFetch<ChatRoom>(
    `/projects/${projectId}/chat?${new URLSearchParams(
      Object.entries(opts)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => [k, String(v)]),
    )}`,
  );

/** Basecamp's "Change dates": move every open date in a to-do list or group by `days`. */
export const shiftDates = (id: number, days: number) =>
  send<{ shifted: number; item: Item }>('POST', `/items/${id}/shift`, { days });

/** Basecamp's Markdown import: headings make lists (groups, inside a list), lines to-dos, indented lines subtasks. */
export const importTodos = (projectId: number, text: string, parentId?: number) =>
  send<{ lists: number; groups: number; todos: number; subtasks: number; completed: number }>(
    'POST',
    `/projects/${projectId}/todos/import`,
    { text, ...(parentId ? { parent_id: parentId } : {}) },
  );
