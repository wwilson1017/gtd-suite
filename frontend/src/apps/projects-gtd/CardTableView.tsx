// Projects GTD — the Card Table as a table, Trello's Table view: one row a card,
// its column, people, labels and dates, edited in place; sorted by any heading.
// The board's filters apply here too.
import { useMemo, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { moveCard, updateCard } from './api';
import type { Board, Card } from './types';
import { AvatarStack, day } from './ui';

type Key = 'title' | 'column' | 'due' | 'start';

export function CardTableView({
  board,
  cards,
  today,
  onOpen,
  reload,
  setError,
}: {
  board: Board;
  cards: Card[];
  today: string;
  onOpen: (card: Card) => void;
  reload: () => Promise<unknown>;
  setError: (msg: string) => void;
}) {
  const [sort, setSort] = useState<{ key: Key; up: boolean }>({ key: 'column', up: true });
  const order = useMemo(() => new Map(board.columns.map((c, i) => [c.id, i])), [board.columns]);
  const rows = useMemo(() => {
    const value = (c: Card): string | number =>
      sort.key === 'title'
        ? c.title.toLowerCase()
        : sort.key === 'column'
          ? (order.get(c.column_id) ?? 0) * 100000 + c.position
          : sort.key === 'due'
            ? (c.due_date ?? '9999')
            : (c.starts_on ?? '9999');
    return [...cards].sort((a, b) => {
      const x = value(a),
        y = value(b);
      return (x < y ? -1 : x > y ? 1 : 0) * (sort.up ? 1 : -1);
    });
  }, [cards, sort, order]);
  const write = async (job: () => Promise<unknown>) => {
    try {
      await job();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save that.'));
    }
    await reload();
  };
  const head = (key: Key, label: string) => (
    <th scope="col" className="px-2 py-2 text-left">
      <button
        type="button"
        className="font-bold hover:underline"
        aria-label={`Sort by ${label}`}
        onClick={() => setSort((s) => ({ key, up: s.key === key ? !s.up : true }))}
      >
        {label}
        {sort.key === key ? (sort.up ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  );
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-[14px]">
        <thead className="border-b-2 border-bc-line text-bc-subtle">
          <tr>
            <th scope="col" className="w-8 px-2">
              <span className="sr-only">Done</span>
            </th>
            {head('title', 'Card')}
            {head('column', 'Column')}
            <th scope="col" className="px-2 text-left">
              People
            </th>
            <th scope="col" className="px-2 text-left">
              Labels
            </th>
            {head('start', 'Starts')}
            {head('due', 'Due')}
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const late = !!c.due_date && !c.completed && c.due_date < today;
            return (
              <tr key={c.id} className="border-b border-bc-line hover:bg-bc-wash">
                <td className="px-2">
                  <input
                    type="checkbox"
                    className="bc-checkbox"
                    checked={!!c.completed}
                    aria-label={`Done: ${c.title}`}
                    disabled={board.status !== 'active'}
                    onChange={() => void write(() => updateCard(c.id, { completed: !c.completed, version: c.version }))}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <button type="button" className="text-left font-semibold hover:underline" onClick={() => onOpen(c)}>
                    {c.title}
                    {c.repeat ? ' 🔁' : ''}
                    {c.template ? ' (template)' : ''}
                  </button>
                </td>
                <td className="px-2">
                  <select
                    value={c.column_id}
                    aria-label={`Column of ${c.title}`}
                    disabled={board.status !== 'active'}
                    className="bc-input w-auto py-0.5 text-[13px]"
                    onChange={(e) => void write(() => moveCard(c.id, Number(e.target.value)))}
                  >
                    {board.columns.map((col) => (
                      <option key={col.id} value={col.id}>
                        {col.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-2">
                  {(c.assignees?.length ?? 0) > 0 && <AvatarStack people={c.assignees!} size={20} max={4} />}
                </td>
                <td className="px-2">
                  <span className="flex flex-wrap gap-1">
                    {(c.labels ?? []).map((l) => (
                      <span
                        key={l.id}
                        className={`bc-c-${l.color} rounded px-1.5 text-[12px] font-semibold text-white`}
                        style={{ background: 'var(--c, #888)' }}
                      >
                        {l.name || ' '}
                      </span>
                    ))}
                  </span>
                </td>
                <td className="px-2">
                  <input
                    type="date"
                    value={c.starts_on ?? ''}
                    aria-label={`Starts: ${c.title}`}
                    disabled={board.status !== 'active'}
                    className="bc-input w-auto py-0.5 text-[13px]"
                    onChange={(e) =>
                      void write(() => updateCard(c.id, { starts_on: e.target.value || null, version: c.version }))
                    }
                  />
                </td>
                <td className={`px-2 ${late ? 'text-bc-unread' : ''}`}>
                  <input
                    type="date"
                    value={c.due_date ?? ''}
                    aria-label={`Due: ${c.title}`}
                    disabled={board.status !== 'active'}
                    title={c.due_date ? day(c.due_date) : ''}
                    className="bc-input w-auto py-0.5 text-[13px]"
                    onChange={(e) =>
                      void write(() => updateCard(c.id, { due_date: e.target.value || null, version: c.version }))
                    }
                  />
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="py-6 text-center text-bc-subtle">
                No cards match.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
