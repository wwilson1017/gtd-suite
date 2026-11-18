import { describe, expect, it } from 'vitest';
import { GROUPS, LISTS, PRIMARY, SECONDARY, overflowHidden, shellMode } from './menu';

const labels = (items: { label: string }[]) => items.map((i) => i.label);

describe('the menu definition', () => {
  it('splits the ten lists into the two tiers, in order', () => {
    expect(labels(PRIMARY)).toEqual(['Today', 'Inbox', 'To Do', 'Contexts', 'Projects']);
    expect(labels(SECONDARY)).toEqual(['Areas', 'Waiting', 'Someday', 'Review', 'Done']);
  });

  it('groups them for the sidebar', () => {
    expect(GROUPS.map((g) => [g.label, labels(g.items)])).toEqual([
      ['Do', ['Today', 'Inbox', 'To Do', 'Contexts']],
      ['Organize', ['Projects', 'Areas']],
      ['Parked', ['Waiting', 'Someday']],
      ['Reflect', ['Review', 'Done']],
    ]);
  });

  it('keeps the existing routes', () => {
    expect(Object.fromEntries(LISTS.map((l) => [l.key, l.sub]))).toEqual({
      today: '',
      inbox: '/inbox',
      next: '/next',
      search: '/search',
      projects: '/projects',
      areas: '/areas',
      waiting: '/waiting',
      someday: '/someday',
      review: '/review',
      done: '/done',
    });
  });
});

describe('shellMode', () => {
  it('uses the bottom bar on a phone whatever the preference', () => {
    expect(shellMode('top', true, false)).toBe('phone');
    expect(shellMode('sidebar', true, false)).toBe('phone');
  });

  it('shows the sidebar only when chosen AND the screen is wide', () => {
    expect(shellMode('sidebar', false, true)).toBe('sidebar');
    expect(shellMode('sidebar', false, false)).toBe('top');
    expect(shellMode('top', false, true)).toBe('top');
  });
});

describe('overflowHidden', () => {
  const W = [50, 60, 70, 55, 45]; // 280 in all
  const MORE = 60;

  it('hides nothing when everything fits', () => {
    expect(overflowHidden(W, 280, MORE, -1)).toEqual([]);
    expect(overflowHidden(W, 500, MORE, 3)).toEqual([]);
  });

  it('collapses from the right, leaving room for More', () => {
    // 279 - 60 = 219 for items: 50 + 60 + 70 = 180 fits, +55 does not.
    expect(overflowHidden(W, 279, MORE, -1)).toEqual([3, 4]);
    expect(overflowHidden(W, 169, MORE, -1)).toEqual([1, 2, 3, 4]);
  });

  it('does not let a narrow later item jump the queue', () => {
    // 119 - 60 = 59 for items: the 50 fits, the 60 does not — so the 10 goes too.
    expect(overflowHidden([50, 60, 10], 119, MORE, -1)).toEqual([1, 2]);
  });

  it('puts every item in More when there is no room', () => {
    expect(overflowHidden(W, 80, MORE, -1)).toEqual([0, 1, 2, 3, 4]);
    expect(overflowHidden(W, 0, MORE, -1)).toEqual([0, 1, 2, 3, 4]);
  });

  it('never hides the current item', () => {
    // Done (index 4) is current: it is reserved first, then the rest fill from the left.
    expect(overflowHidden(W, 279, MORE, 4)).toEqual([2, 3]);
    expect(overflowHidden(W, 0, MORE, 2)).toEqual([0, 1, 3, 4]);
    for (let available = 0; available < 280; available += 7) {
      for (let current = 0; current < W.length; current++) {
        expect(overflowHidden(W, available, MORE, current)).not.toContain(current);
      }
    }
  });
});
