// @vitest-environment jsdom
//
// Projects GTD work assigned to the person, on Todo's To Do page: the "From Projects
// GTD" group. It lists their to-dos and cards with each one's project and due date,
// and a check here is the write Projects GTD makes: a to-do through its complete
// call, a card through its update with the version read. A checked row stays, struck
// through, with its own Undo: a to-do is un-checked, a card goes back in one move to
// the column and On Hold it was read in, naming the version its completion answered.
// A card row shows what each write answered, so a Card Table rule that moved the card
// in or out of Done shows. A card that changed meanwhile is never overwritten. The group is absent with
// Projects GTD off and with nothing assigned.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../core/api/client';
import type { Card, Item } from '../projects-gtd/types';
import type { Session, Todo } from './types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(),
  getFilters: vi.fn(),
  listProjects: vi.fn(),
  listTodos: vi.fn(),
  updateTodo: vi.fn(),
  createTodo: vi.fn(),
}));
vi.mock('./api', () => api);
const projects = vi.hoisted(() => ({
  getAssignments: vi.fn(),
  completeItem: vi.fn(),
  updateCard: vi.fn(),
  moveCard: vi.fn(),
}));
vi.mock('../projects-gtd/api', async (original) => ({
  ...(await original<typeof import('../projects-gtd/api')>()),
  ...projects,
}));

import { CARD_CHANGED } from '../projects-gtd/api';
import { NextActionsPage } from './NextActionsPage';
import { bootstrap, resetSession } from './session';
import { resetUndoQueue, takeAll } from './undoQueue';
import { dueLabel, todayStr } from './util';

const HERE = window.location.origin;
const SESSION: Session = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['todo', 'notes', 'projects'],
};
const AT = '2026-11-01T12:00:00Z';

/** One of Todo's own next actions, numbered like the Projects GTD to-do below. */
const OWN: Todo = {
  id: 11,
  title: 'Water the herbs',
  notes: '',
  project_id: null,
  project_name: null,
  context: '@home',
  tags: [],
  status: 'next_action',
  star: false,
  due_date: null,
  repeat: '',
  auto_star_on_due: false,
  source: 'ui',
  created_at: AT,
  updated_at: AT,
  completed_at: null,
};

function todo(over: Partial<Item> = {}): Item {
  return {
    id: 11,
    board_id: 31,
    board_name: 'Open the patio',
    parent_id: 40,
    card_id: null,
    type: 'todo',
    title: 'Book the inspection',
    body: '',
    status: 'active',
    position: 0,
    category: '',
    color: '',
    starts_on: null,
    due_on: '2026-12-04',
    completed: false,
    completed_at: null,
    completer: null,
    assignees: [],
    creator: null,
    source: 'ui',
    source_client: null,
    version: 1,
    created_at: AT,
    updated_at: AT,
    comments_count: 0,
    ...over,
  };
}

/** A card in "Doing" (column 52), the second work column. */
function card(over: Partial<Card> = {}): Card {
  return {
    id: 21,
    board_id: 31,
    board_name: 'Open the patio',
    column_id: 52,
    column_name: 'Doing',
    column_kind: 'column',
    title: 'Order the umbrellas',
    notes: '',
    due_date: null,
    on_hold: false,
    completed: false,
    position: 3,
    status: 'active',
    source: 'ui',
    source_client: null,
    version: 4,
    created_at: AT,
    updated_at: AT,
    ...over,
  };
}

/** The same card as its completion answers it: in Done, off hold, one version on. */
const completed = (c: Card): Card => ({
  ...c,
  column_id: 59,
  column_name: 'Done',
  column_kind: 'done',
  on_hold: false,
  completed: true,
  version: c.version + 1,
});

const changed = () => new ApiError(409, 'This card changed since it was opened.', 'API error 409');

let container: HTMLDivElement;
let root: Root;

async function show(apps = SESSION.apps) {
  resetSession();
  api.getSession.mockResolvedValue({ ...SESSION, apps });
  await act(async () => {
    await bootstrap();
  });
  await act(async () => {
    root.render(
      <MemoryRouter>
        <NextActionsPage />
      </MemoryRouter>,
    );
  });
  await act(async () => {
    await Promise.resolve();
  });
}

const group = () => container.querySelector('section[aria-label="From Projects GTD"]');
const rows = () => [...(group()?.querySelectorAll(':scope > div > div') ?? [])];
const row = (title: string) => rows().find((r) => r.querySelector('p')!.textContent!.startsWith(title))!;
const box = (title: string) => row(title).querySelector<HTMLInputElement>('input[type="checkbox"]')!;
const undo = (title: string) => row(title).querySelector<HTMLButtonElement>('button');
const struck = (title: string) => row(title).querySelector('p')!.className.includes('line-through');
const alerts = (within: Element | null) =>
  [...(within?.querySelectorAll('[role="alert"]') ?? [])].map((a) => a.textContent);
const due = (day: string) => dueLabel(day, todayStr()).text;
const click = (el: Element) =>
  act(async () => {
    (el as HTMLElement).click();
  });

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  resetUndoQueue();
  // One address for the whole file (hop.ts asks once per page load): a title opens the item itself.
  api.getConfig.mockResolvedValue({
    app: 'todo',
    apps: {
      todo: { title: 'Todo GTD', url: HERE },
      projects: { title: 'Projects GTD', url: `${HERE}/projects` },
    },
  });
  api.getFilters.mockResolvedValue({ contexts: ['@home'], tags: [], status_counts: {} });
  api.listProjects.mockResolvedValue([]);
  api.listTodos.mockResolvedValue([OWN]);
  projects.getAssignments.mockResolvedValue({ todos: [todo()], cards: [card()] });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  vi.useRealTimers();
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe('the "From Projects GTD" group', () => {
  it('lists the to-dos and cards assigned to the person, soonest due first, with project and due date', async () => {
    projects.getAssignments.mockResolvedValue({
      todos: [
        todo(),
        todo({ id: 12, title: 'Call the awning company', board_id: 32, board_name: 'Spring menu', due_on: null }),
      ],
      cards: [card({ due_date: '2026-12-01' })],
    });
    await show();

    expect(projects.getAssignments).toHaveBeenCalledExactlyOnceWith();
    // The whole group: no badge, nothing marked as new.
    expect(group()!.querySelector('h2')!.textContent).toBe('From Projects GTD');
    expect(rows().map((r) => r.textContent)).toEqual([
      `Order the umbrellas${due('2026-12-01')}Open the patio`,
      `Book the inspection${due('2026-12-04')}Open the patio`,
      'Call the awning companySpring menu',
    ]);
    // A title opens the item in Projects GTD: a card on its board, a to-do on its own page.
    expect(rows().map((r) => r.querySelector('a')!.getAttribute('href'))).toEqual([
      `${HERE}/projects/app/p/31/cards?card=21`,
      `${HERE}/projects/app/i/11`,
      `${HERE}/projects/app/i/12`,
    ]);
    // Nothing is copied into Todo: its own list still counts its own.
    expect(container.textContent).toContain('1 next action');
    expect(group()!.textContent).not.toContain('Water the herbs');
  });

  it('checks a to-do off in Projects GTD and keeps the row, struck through; Undo re-opens it', async () => {
    projects.completeItem.mockResolvedValue(todo({ completed: true }));
    await show();

    await click(box('Book the inspection'));
    expect(projects.completeItem).toHaveBeenCalledExactlyOnceWith(11, true);
    expect([box('Book the inspection').checked, struck('Book the inspection')]).toEqual([true, true]);
    // Not through Todo's own writes or its undo queue, where 11 is "Water the herbs".
    expect(api.updateTodo).not.toHaveBeenCalled();
    expect(takeAll()).toEqual([]);
    expect(projects.getAssignments).toHaveBeenCalledTimes(1);

    await click(undo('Book the inspection')!);
    expect(projects.completeItem.mock.calls).toEqual([
      [11, true],
      [11, false],
    ]);
    expect([box('Book the inspection').checked, struck('Book the inspection')]).toEqual([false, false]);
    expect(undo('Book the inspection')).toBeNull();
    expect(projects.updateCard).not.toHaveBeenCalled();
    expect(projects.moveCard).not.toHaveBeenCalled();
  });

  it('completes a card with the version read; Undo is one move back to its column', async () => {
    const read = card();
    projects.updateCard.mockResolvedValue(completed(read));
    projects.moveCard.mockResolvedValue({ ...read, position: 5, version: 6 });
    await show();

    await click(box('Order the umbrellas'));
    expect(projects.updateCard).toHaveBeenCalledExactlyOnceWith(21, { completed: true, version: 4 });
    expect(projects.completeItem).not.toHaveBeenCalled();
    expect(struck('Order the umbrellas')).toBe(true);

    // Back to "Doing", a later work column (a plain re-open would pick the first), off
    // hold, at no particular place, naming the version the completion answered.
    await click(undo('Order the umbrellas')!);
    expect(projects.moveCard).toHaveBeenCalledExactlyOnceWith(21, 52, undefined, false, 5);
    expect(projects.updateCard).toHaveBeenCalledTimes(1);
    expect([box('Order the umbrellas').checked, struck('Order the umbrellas')]).toEqual([false, false]);

    // Checked again, it names the version the move answered.
    await click(box('Order the umbrellas'));
    expect(projects.updateCard).toHaveBeenLastCalledWith(21, { completed: true, version: 6 });
  });

  it('puts a card that was On Hold back On Hold', async () => {
    const read = card({ on_hold: true });
    projects.getAssignments.mockResolvedValue({ todos: [], cards: [read] });
    projects.updateCard.mockResolvedValue(completed(read));
    projects.moveCard.mockResolvedValue({ ...read, version: 6 });
    await show();

    await click(box('Order the umbrellas'));
    await click(box('Order the umbrellas')); // un-ticking the box is the same Undo
    expect(projects.moveCard).toHaveBeenCalledExactlyOnceWith(21, 52, undefined, true, 5);
    expect(struck('Order the umbrellas')).toBe(false);
  });

  it('shows a card as its completion answered when a rule moved it straight out of Done', async () => {
    // A Card Table rule on "card completed" moves it to Review (column 53), open.
    projects.updateCard.mockResolvedValue({ ...card(), column_id: 53, column_name: 'Review', version: 6 });
    await show();

    await click(box('Order the umbrellas'));
    expect([box('Order the umbrellas').checked, struck('Order the umbrellas')]).toEqual([false, false]);
    expect(undo('Order the umbrellas')).toBeNull();

    // Checked again, it names the version that answer carried, and Undo still goes back
    // to the column it was read in.
    projects.updateCard.mockResolvedValue(completed(card({ version: 6 })));
    projects.moveCard.mockResolvedValue({ ...card(), version: 8 });
    await click(box('Order the umbrellas'));
    expect(projects.updateCard).toHaveBeenLastCalledWith(21, { completed: true, version: 6 });
    expect(struck('Order the umbrellas')).toBe(true);
    await click(undo('Order the umbrellas')!);
    expect(projects.moveCard).toHaveBeenCalledExactlyOnceWith(21, 52, undefined, false, 7);
  });

  it('keeps a card checked when a rule completed it again after Undo', async () => {
    projects.updateCard.mockResolvedValue(completed(card()));
    // A rule on a move into "Doing" sends it to Done.
    projects.moveCard.mockResolvedValueOnce(completed(card({ version: 5 })));
    await show();

    await click(box('Order the umbrellas'));
    await click(undo('Order the umbrellas')!);
    expect([box('Order the umbrellas').checked, struck('Order the umbrellas')]).toEqual([true, true]);
    expect(undo('Order the umbrellas')).not.toBeNull();

    // The next Undo names the version the move answered.
    projects.moveCard.mockResolvedValueOnce({ ...card(), version: 7 });
    await click(undo('Order the umbrellas')!);
    expect(projects.moveCard).toHaveBeenLastCalledWith(21, 52, undefined, false, 6);
    expect(struck('Order the umbrellas')).toBe(false);
  });

  it('overwrites nothing when the card changed between completing and Undo', async () => {
    projects.updateCard.mockResolvedValue(completed(card()));
    projects.moveCard.mockRejectedValue(changed());
    await show();
    await click(box('Order the umbrellas'));
    // Someone re-opened and renamed it meanwhile; the group shows it as it is now.
    projects.getAssignments.mockResolvedValue({
      todos: [todo()],
      cards: [card({ title: 'Order six umbrellas', column_id: 51, version: 7 })],
    });

    await click(undo('Order the umbrellas')!);
    expect(projects.moveCard).toHaveBeenCalledExactlyOnceWith(21, 52, undefined, false, 5);
    expect(projects.updateCard).toHaveBeenCalledTimes(1); // no second write of any kind
    expect(alerts(group())).toEqual([CARD_CHANGED]);
    expect(projects.getAssignments).toHaveBeenCalledTimes(2);
    expect([box('Order six umbrellas').checked, struck('Order six umbrellas')]).toEqual([false, false]);
  });

  it('says so and shows the latest when the card changed before it was checked', async () => {
    projects.updateCard.mockRejectedValueOnce(changed());
    await show();
    projects.getAssignments.mockResolvedValue({ todos: [], cards: [] }); // completed somewhere else

    await click(box('Order the umbrellas'));
    expect(projects.getAssignments).toHaveBeenCalledTimes(2);
    // The message outlives the rows it was about.
    expect(rows()).toEqual([]);
    expect(alerts(group())).toEqual([CARD_CHANGED]);
  });

  it('leaves the row unchecked, with the reason, when a completion fails', async () => {
    const why = 'This to-do is in the trash.';
    projects.completeItem.mockRejectedValue(new ApiError(400, why, `API error 400: ${why}`));
    projects.updateCard.mockRejectedValue(new TypeError('Failed to fetch'));
    await show();

    await click(box('Book the inspection'));
    await click(box('Order the umbrellas'));
    expect([box('Book the inspection').checked, struck('Book the inspection')]).toEqual([false, false]);
    expect(alerts(row('Book the inspection'))).toEqual([why]);
    expect([box('Order the umbrellas').checked, box('Order the umbrellas').disabled]).toEqual([false, false]);
    expect(alerts(row('Order the umbrellas'))).toEqual(['Failed to fetch']);
    expect(undo('Book the inspection')).toBeNull();
    expect(projects.getAssignments).toHaveBeenCalledTimes(1);

    // The next try clears the line.
    projects.completeItem.mockResolvedValue(todo({ completed: true }));
    await click(box('Book the inspection'));
    expect(alerts(row('Book the inspection'))).toEqual([]);
    expect(struck('Book the inspection')).toBe(true);
  });

  it('keeps a completed row with the reason when its Undo fails', async () => {
    projects.completeItem.mockResolvedValueOnce(todo({ completed: true })).mockRejectedValueOnce(new Error('Offline'));
    await show();
    await click(box('Book the inspection'));
    await click(undo('Book the inspection')!);
    expect([box('Book the inspection').checked, struck('Book the inspection')]).toEqual([true, true]);
    expect(alerts(row('Book the inspection'))).toEqual(['Offline']);
    expect(undo('Book the inspection')!.disabled).toBe(false);
  });

  it('is one press: the box is off while the request is out', async () => {
    let finish!: (done: Item) => void;
    projects.completeItem.mockReturnValue(new Promise<Item>((resolve) => (finish = resolve)));
    await show();
    await click(box('Book the inspection'));
    expect(box('Book the inspection').disabled).toBe(true);
    await click(box('Book the inspection'));
    expect(projects.completeItem).toHaveBeenCalledTimes(1);
    await act(async () => {
      finish(todo({ completed: true }));
    });
    expect([box('Book the inspection').disabled, struck('Book the inspection')]).toEqual([false, true]);
  });

  it('checks off a repeating to-do and card as any other; the next one waits for a reload', async () => {
    const weekly = card({ repeat: 'every_week' });
    projects.getAssignments.mockResolvedValue({ todos: [todo({ repeat: 'every_week' })], cards: [weekly] });
    projects.completeItem.mockResolvedValue(todo({ completed: true }));
    projects.updateCard.mockResolvedValue(completed(weekly));
    projects.moveCard.mockResolvedValue({ ...weekly, version: 6 });
    await show();
    expect(rows().map((r) => r.querySelector('[aria-label="Repeats"]') !== null)).toEqual([true, true]);

    await click(box('Book the inspection'));
    await click(box('Order the umbrellas'));
    // Projects GTD made the next ones; this page shows what it read, until it reloads.
    expect(projects.getAssignments).toHaveBeenCalledTimes(1);
    expect(rows()).toHaveLength(2);

    // Undo re-opens the ones that were checked, by their own ids.
    await click(undo('Book the inspection')!);
    await click(undo('Order the umbrellas')!);
    expect(projects.completeItem).toHaveBeenLastCalledWith(11, false);
    expect(projects.moveCard).toHaveBeenCalledExactlyOnceWith(21, 52, undefined, false, 5);
    expect(projects.getAssignments).toHaveBeenCalledTimes(1);
    expect(rows()).toHaveLength(2);
  });

  it("follows the page's filter: its text on title and project, and no rows under a context", async () => {
    projects.getAssignments.mockResolvedValue({
      todos: [todo(), todo({ id: 12, title: 'Call the awning company', board_name: 'Spring menu' })],
      cards: [],
    });
    await show();
    vi.useFakeTimers(); // the filter box settles a quarter second after the last key
    const input = container.querySelector<HTMLInputElement>('input[placeholder="Filter…"]')!;
    const type = (text: string) =>
      act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, text);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await vi.advanceTimersByTimeAsync(300);
      });

    await type('PATIO');
    expect(rows().map((r) => r.querySelector('p')!.textContent)).toEqual(['Book the inspection']);
    await type('awning');
    expect(rows().map((r) => r.querySelector('p')!.textContent)).toEqual(['Call the awning company']);
    await type('nothing like it');
    expect(group()).toBeNull();
    await type('');
    expect(rows()).toHaveLength(2);

    const button = (label: string) =>
      [...container.querySelectorAll('button')].find((b) => b.textContent?.trim() === label)!;
    await click(button('Filters'));
    await click(button('@home'));
    expect(group()).toBeNull();
  });

  it('is absent when nothing is assigned', async () => {
    projects.getAssignments.mockResolvedValue({ todos: [], cards: [] });
    await show();
    expect(projects.getAssignments).toHaveBeenCalledTimes(1);
    expect(group()).toBeNull();
    expect(container.textContent).not.toContain('From Projects GTD');
  });

  it('is absent, and asks for nothing, with Projects GTD off', async () => {
    await show(['todo', 'notes']);
    expect(container.textContent).toContain('Water the herbs');
    expect(projects.getAssignments).not.toHaveBeenCalled();
    expect(group()).toBeNull();
  });

  it('leaves the page as it was when the assignments cannot be read', async () => {
    projects.getAssignments.mockRejectedValue(new Error('Offline'));
    await show();
    expect(container.textContent).toContain('Water the herbs');
    expect(group()).toBeNull();
  });
});
