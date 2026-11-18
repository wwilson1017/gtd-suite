// @vitest-environment jsdom
//
// The card sheet's write queue: a tap that lands while a notes save is out runs after
// it; a failed save drops what is queued behind it; and a queued move that comes back
// with an AI's edit shows that edit, so the next blur does not overwrite it.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../core/api/client';
import type { Board, Card } from './types';

const api = vi.hoisted(() => ({
  updateCard: vi.fn(),
  moveCard: vi.fn(),
  // The card's comments and boosts (CardThread): an empty discussion.
  cardThread: vi.fn(() => Promise.resolve({ comments: [], subtasks: [], boosts: [] })),
  boostCard: vi.fn(),
  boostItem: vi.fn(),
  commentOnCard: vi.fn(),
  removeBoost: vi.fn(),
  completeItem: vi.fn(),
  createItem: vi.fn(),
  createCard: vi.fn(),
  updateItem: vi.fn(),
}));
vi.mock('./api', () => api);

import { CardSheet } from './CardSheet';

const CARD: Card = {
  id: 1,
  board_id: 1,
  board_name: 'B',
  column_id: 1,
  column_name: 'To do',
  title: 'T',
  notes: 'A',
  due_date: null,
  position: 0,
  status: 'active',
  source: 'ui',
  source_client: null,
  version: 1,
  created_at: '2026-10-12T00:00:00Z',
  updated_at: '2026-10-12T00:00:00Z',
};
const BOARD: Board = {
  id: 1,
  name: 'B',
  notes: '',
  status: 'active',
  updated_at: '',
  archived_cards: 0,
  columns: [
    { id: 1, board_id: 1, name: 'To do', position: 0, done: false, cards: [CARD] },
    { id: 2, board_id: 1, name: 'Done', position: 1, done: true, cards: [] },
  ],
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let onClose: ReturnType<typeof vi.fn<() => void>>;

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  api.updateCard.mockReset();
  api.moveCard.mockReset();
  onClose = vi.fn<() => void>();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<CardSheet card={CARD} board={BOARD} onClose={onClose} reload={async () => null} />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const notes = () => host.querySelector('textarea')!;
const button = (name: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === name)!;

/** Type into the notes and leave them: the blur queues the save. */
async function editNotes(text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(notes(), text);
    notes().dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => {
    notes().dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
  });
}

describe('CardSheet write queue', () => {
  it('runs a Move tapped while a notes save is out, after the save', async () => {
    let finish!: (c: Card) => void;
    api.updateCard.mockReturnValueOnce(
      new Promise<Card>((r) => {
        finish = r;
      }),
    );
    api.moveCard.mockResolvedValueOnce({ ...CARD, notes: 'B', version: 3, column_id: 2, column_name: 'Done' });
    await editNotes('B');
    expect(button('Done').disabled).toBe(false);
    await act(async () => {
      button('Done').click();
    });
    expect(api.moveCard).not.toHaveBeenCalled();
    await act(async () => {
      finish({ ...CARD, notes: 'B', version: 2 });
    });
    expect(api.updateCard).toHaveBeenCalledWith(1, { notes: 'B', version: 1 });
    expect(api.moveCard).toHaveBeenCalledWith(1, 2, undefined);
  });

  it('drops an Archive queued behind a failed save, and keeps the sheet open', async () => {
    let fail!: (e: Error) => void;
    api.updateCard.mockReturnValueOnce(
      new Promise<Card>((_, reject) => {
        fail = reject;
      }),
    );
    await editNotes('B');
    await act(async () => {
      button('Archive card').click();
    });
    await act(async () => {
      fail(new ApiError(422, null, 'Notes are too long.'));
    });
    expect(api.updateCard).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
    expect(notes().value).toBe('B');
  });

  it('shows an AI edit a queued move returns, so the next blur saves nothing', async () => {
    let finish!: (c: Card) => void;
    api.updateCard.mockReturnValueOnce(
      new Promise<Card>((r) => {
        finish = r;
      }),
    );
    api.moveCard.mockResolvedValueOnce({ ...CARD, notes: 'C from the AI', version: 3, column_id: 2 });
    await editNotes('B');
    await act(async () => {
      button('Done').click();
    });
    await act(async () => {
      finish({ ...CARD, notes: 'B', version: 2 });
    });
    expect(notes().value).toBe('C from the AI');
    await act(async () => {
      notes().dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    });
    expect(api.updateCard).toHaveBeenCalledTimes(1);
  });
});

describe('CardSheet subtasks', () => {
  it('makes a subtask a card just below, with its people and date, and archives the subtask', async () => {
    const step = {
      id: 5,
      type: 'step',
      title: 'Order grout',
      completed: false,
      due_on: '2026-11-02',
      assignees: [{ id: 2, name: 'Claude', kind: 'ai', color: '' }],
    };
    api.cardThread.mockResolvedValue({ comments: [], subtasks: [step], boosts: [] } as never);
    api.createCard.mockResolvedValue({ ...CARD, id: 9 });
    api.updateCard.mockResolvedValue({ ...CARD, id: 9 });
    api.updateItem.mockResolvedValue({});
    const second = { ...CARD, id: 2, title: 'U' };
    const board = { ...BOARD, columns: [{ ...BOARD.columns[0], cards: [CARD, second] }, BOARD.columns[1]] };
    act(() => root.unmount()); // the sheet keeps the card it opened with: open this one fresh
    root = createRoot(host);
    await act(async () => {
      root.render(<CardSheet card={second} board={board} onClose={onClose} reload={async () => null} />);
    });
    expect(host.querySelector('[aria-label="0 of 1 subtasks done"]')).not.toBeNull();
    const make = host.querySelector<HTMLButtonElement>('button[aria-label=\'Make "Order grout" a card\']')!;
    await act(async () => {
      make.click();
    });
    expect(api.createCard).toHaveBeenCalledWith(1, 1, 'Order grout', 2); // below card 2, the second
    expect(api.updateCard).toHaveBeenCalledWith(9, { due_date: '2026-11-02', assignee_ids: [2] });
    expect(api.updateItem).toHaveBeenCalledWith(5, { status: 'archived' });
  });

  it("keeps a held card's new card On Hold, and offers nothing on an archived card", async () => {
    const step = { id: 6, type: 'step', title: 'Seal', completed: false, due_on: null, assignees: [] };
    api.cardThread.mockResolvedValue({ comments: [], subtasks: [step], boosts: [] } as never);
    api.createCard.mockResolvedValue({ ...CARD, id: 10 });
    api.updateCard.mockReset().mockResolvedValue({ ...CARD, id: 10 });
    const open = async (card: Card) => {
      act(() => root.unmount());
      root = createRoot(host);
      await act(async () => {
        root.render(<CardSheet card={card} board={BOARD} onClose={onClose} reload={async () => null} />);
      });
    };
    await open({ ...CARD, id: 3, on_hold: true });
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label=\'Make "Seal" a card\']')!.click();
    });
    expect(api.updateCard).toHaveBeenCalledWith(10, { on_hold: true });
    await open({ ...CARD, id: 4, status: 'archived' });
    expect(host.querySelector('button[aria-label=\'Make "Seal" a card\']')).toBeNull();
  });
});
