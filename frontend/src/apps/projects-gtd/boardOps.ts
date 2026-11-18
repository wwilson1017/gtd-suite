// Projects GTD — pure board moves (unit-tested in boardOps.test.ts). The page moves
// a card on screen at once with these, then the server's answer replaces the board.
import type { Board, Card, Position } from './types';

/** `ids` with `item` put at `position`: the server's rule (backend/boards.py _place). */
export function place<T>(items: T[], item: T, position: Position | undefined): T[] {
  const rest = items.filter((i) => i !== item);
  if (position === undefined || position === 'bottom') return [...rest, item];
  if (position === 'top') return [item, ...rest];
  const index = Math.max(0, Math.min(position, rest.length));
  return [...rest.slice(0, index), item, ...rest.slice(index)];
}

/** Where a card dropped in front of the card at `before` (or at the end of the
 *  column, when `before` is null) lands, as an index among the column's OTHER
 *  cards — what the server's `position` means. */
export function dropIndex(board: Board, cardId: number, columnId: number, before: number | null): Position {
  if (before === null) return 'bottom';
  const others = board.columns.find((c) => c.id === columnId)?.cards.filter((c) => c.id !== cardId) ?? [];
  const index = others.findIndex((c) => c.id === before);
  return index < 0 ? 'bottom' : index;
}

/** The board with one card moved: what the screen shows while the server answers. */
export function moveLocal(board: Board, cardId: number, columnId: number, position: Position | undefined): Board {
  const card = board.columns.flatMap((c) => c.cards).find((c) => c.id === cardId);
  const target = board.columns.find((c) => c.id === columnId);
  if (!card || !target) return board;
  const moved: Card = { ...card, column_id: columnId, column_name: target.name };
  const where = position ?? (target.done ? 'top' : 'bottom');
  return {
    ...board,
    columns: board.columns.map((col) => {
      const others = col.cards.filter((c) => c.id !== cardId);
      if (col.id !== columnId) return { ...col, cards: others };
      return { ...col, cards: place([...others, moved], moved, where) };
    }),
  };
}
