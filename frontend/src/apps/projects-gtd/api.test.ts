import { afterEach, describe, expect, it, vi } from 'vitest';
import { moveCard } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('moveCard', () => {
  it('names the version only when given one: a plain move is sent as it always was', async () => {
    const sent: [string, unknown][] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        sent.push([url, JSON.parse(String(init.body))]);
        return { ok: true, status: 200, json: async () => ({}) };
      }),
    );

    await moveCard(7, 3);
    await moveCard(7, 3, 'top', true);
    await moveCard(7, 3, undefined, false, 12);

    expect(sent).toEqual([
      ['/api/app/cards/7/move', { column_id: 3 }],
      ['/api/app/cards/7/move', { column_id: 3, position: 'top', on_hold: true }],
      ['/api/app/cards/7/move', { column_id: 3, on_hold: false, version: 12 }],
    ]);
  });
});
