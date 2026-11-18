import { describe, expect, it } from 'vitest';
import { MAX_SELECTED, toggleSelected } from './CardSelection';

describe('toggleSelected', () => {
  it('adds and removes a card, never past the most Trello allows', () => {
    expect(toggleSelected([1, 2], 3)).toEqual([1, 2, 3]);
    expect(toggleSelected([1, 2, 3], 2)).toEqual([1, 3]);
    const full = Array.from({ length: MAX_SELECTED }, (_, i) => i + 1);
    expect(toggleSelected(full, 99)).toBe(full);
    expect(toggleSelected(full, 5)).toHaveLength(MAX_SELECTED - 1);
  });
});
