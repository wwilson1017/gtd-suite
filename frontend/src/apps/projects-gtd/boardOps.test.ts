import { describe, expect, it } from 'vitest';
import { dropIndex, moveLocal, place } from './boardOps';
import type { Board, Card } from './types';

const card = (id: number, column_id: number): Card => ({
  id,
  board_id: 1,
  board_name: 'B',
  column_id,
  column_name: '',
  title: `c${id}`,
  notes: '',
  due_date: null,
  position: 0,
  status: 'active',
  source: 'ui',
  source_client: null,
  version: 1,
  created_at: '',
  updated_at: '',
});

const board: Board = {
  id: 1,
  name: 'B',
  notes: '',
  status: 'active',
  updated_at: '',
  archived_cards: 0,
  columns: [
    { id: 10, board_id: 1, name: 'To do', position: 0, done: false, cards: [card(1, 10), card(2, 10), card(3, 10)] },
    { id: 11, board_id: 1, name: 'Done', position: 1, done: true, cards: [card(4, 11)] },
  ],
};

const ids = (b: Board) => b.columns.map((c) => c.cards.map((x) => x.id));

describe('board moves', () => {
  it('places like the server', () => {
    expect(place([1, 2, 3], 3, 0)).toEqual([3, 1, 2]);
    expect(place([1, 2, 3], 1, 'bottom')).toEqual([2, 3, 1]);
    expect(place([1, 2, 3], 2, 99)).toEqual([1, 3, 2]);
  });

  it('dropping in front of a card below it in the same column lands just above that card', () => {
    // Card 1 dropped in front of card 3: among the others [2, 3], that is index 1.
    const at = dropIndex(board, 1, 10, 3);
    expect(at).toBe(1);
    expect(ids(moveLocal(board, 1, 10, at))).toEqual([[2, 1, 3], [4]]);
  });

  it('a card moved to the done column goes on top unless told otherwise', () => {
    expect(ids(moveLocal(board, 2, 11, undefined))).toEqual([
      [1, 3],
      [2, 4],
    ]);
    expect(ids(moveLocal(board, 2, 11, dropIndex(board, 2, 11, null)))).toEqual([
      [1, 3],
      [4, 2],
    ]);
  });
});
