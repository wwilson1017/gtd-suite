import { afterEach, describe, expect, it, vi } from 'vitest';
import { listTodos } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('listTodos', () => {
  it('pages an open list by offset until a short page comes back', async () => {
    // Exactly two full pages: the list is only known to be finished when a third,
    // empty page answers.
    const rows = Array.from({ length: 1000 }, (_, i) => ({ id: i + 1 }));
    const asked: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const q = new URL(url, 'http://x').searchParams;
        asked.push(`${q.get('status') ?? q.get('search')} ${q.get('limit')}@${q.get('offset')}`);
        const from = Number(q.get('offset'));
        const todos = rows.slice(from, from + Number(q.get('limit')));
        return { ok: true, status: 200, json: async () => ({ todos }) };
      }),
    );

    const all = await listTodos({ status: 'next_action', limit: 500 });

    expect(asked).toEqual(['next_action 500@0', 'next_action 500@500', 'next_action 500@1000']);
    expect(all.map((t) => t.id)).toEqual(rows.map((r) => r.id));

    // Done, Dropped and a search stay one window of `limit` rows.
    asked.length = 0;
    expect(await listTodos({ status: 'done', limit: 200 })).toHaveLength(200);
    expect(await listTodos({ status: 'dropped', limit: 200 })).toHaveLength(200);
    expect(await listTodos({ search: 'milk', limit: 500 })).toHaveLength(500);
    expect(asked).toEqual(['done 200@null', 'dropped 200@null', 'milk 500@null']);
  });
});
