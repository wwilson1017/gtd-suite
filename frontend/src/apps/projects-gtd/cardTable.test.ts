// The Card Table's filter (Trello's: words, person, label, due) and its date chip
// (Trello's five states), as BoardPage applies them.
import { describe, expect, it } from 'vitest';
import { matches, type Filter } from './BoardPage';
import { dueTone } from './ui';
import type { Card } from './types';

const card = (over: Partial<Card>): Card => ({
  id: 1,
  board_id: 1,
  board_name: 'B',
  column_id: 1,
  column_name: 'Triage',
  title: 'Order tile',
  notes: '',
  due_date: null,
  position: 0,
  status: 'active',
  source: 'ui',
  source_client: null,
  version: 1,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
  assignees: [],
  labels: [],
  ...over,
});
const none: Filter = { text: '', person: '', label: '', due: '' };
const today = '2026-10-13';

describe('the card filter', () => {
  it('matches words in the title or notes, any case', () => {
    expect(matches(card({ notes: 'Call the TILER' }), { ...none, text: 'tiler' }, 1, today)).toBe(true);
    expect(matches(card({}), { ...none, text: 'paint' }, 1, today)).toBe(false);
  });
  it('finds my cards and a label', () => {
    const mine = card({
      assignees: [{ id: 7, name: 'Me', kind: 'me', color: '' }],
      labels: [{ id: 3, name: 'Bug', color: 'red' }],
    });
    expect(matches(mine, { ...none, person: 'me' }, 7, today)).toBe(true);
    expect(matches(mine, { ...none, person: 'me' }, 8, today)).toBe(false);
    expect(matches(mine, { ...none, label: '3' }, 7, today)).toBe(true);
    expect(matches(mine, { ...none, label: '4' }, 7, today)).toBe(false);
  });
  it('filters by due: overdue, the next week, none', () => {
    expect(matches(card({ due_date: '2026-10-12' }), { ...none, due: 'overdue' }, 1, today)).toBe(true);
    expect(matches(card({ due_date: '2026-10-12', completed: true }), { ...none, due: 'overdue' }, 1, today)).toBe(
      false,
    );
    expect(matches(card({ due_date: '2026-10-20' }), { ...none, due: 'week' }, 1, today)).toBe(true);
    expect(matches(card({ due_date: '2026-10-21' }), { ...none, due: 'week' }, 1, today)).toBe(false);
    expect(matches(card({}), { ...none, due: 'none' }, 1, today)).toBe(true);
  });
  it('filters done or not, and a filter saved before that ignores it', () => {
    expect(matches(card({ completed: true }), { ...none, done: 'open' }, 1, today)).toBe(false);
    expect(matches(card({ completed: true }), { ...none, done: 'done' }, 1, today)).toBe(true);
    expect(matches(card({}), { ...none, done: 'done' }, 1, today)).toBe(false);
    expect(matches(card({ completed: true }), none, 1, today)).toBe(true);
  });
});

describe('the due chip', () => {
  it('runs grey, yellow, red, pink, and green when done', () => {
    expect(dueTone('2026-10-20', false, today)).toContain('bg-bc-wash');
    expect(dueTone('2026-10-14', false, today)).toContain('#f5cd47');
    expect(dueTone('2026-10-12', false, today)).toContain('#c9372c');
    expect(dueTone('2026-10-01', false, today)).toContain('#ffedeb');
    expect(dueTone('2026-10-01', true, today)).toContain('#e3fcef');
  });
});
