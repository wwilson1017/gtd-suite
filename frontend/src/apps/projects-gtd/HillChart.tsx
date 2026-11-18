// Projects GTD — Hill Charts, as Basecamp draws them: a hill with "Figuring
// things out" up the left and "Making it happen" down the right, each tracked
// to-do list a coloured dot on it. Only the person moves the dots (drag them,
// add a note, save): every save is kept as an update, and a hill nobody moved
// for two weeks says so. AI tools read it.
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { getHill, setHill } from './api';
import type { HillChart, HillList, Item } from './types';
import { Avatar, when } from './ui';

const W = 600;
const H = 170;
const BASE = 150;
const PEAK = 120;
// Dot colours for lists with none, in Basecamp's palette order.
const FALLBACK = ['#42a3ff', '#f58e02', '#56b66f', '#ae80ff', '#ef63b8', '#0db3c1'];

const yAt = (x: number) => BASE - PEAK * Math.sin((Math.PI * x) / W);
const CURVE = `M 0 ${BASE} ${Array.from({ length: 61 }, (_, i) => `L ${i * 10} ${yAt(i * 10).toFixed(1)}`).join(' ')}`;

/** The hill with its dots. With `onMove`, the dots drag along it. */
export function Hill({
  lists,
  onMove,
  small = false,
}: {
  lists: HillList[];
  onMove?: (id: number, hill: number) => void;
  small?: boolean;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [held, setHeld] = useState<number | null>(null);
  const place = (clientX: number) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return 0;
    return Math.max(0, Math.min(100, ((clientX - box.left) / box.width) * 100));
  };
  return (
    <svg
      ref={svg}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Hill Chart"
      className={`w-full touch-none select-none ${small ? 'max-h-24' : ''}`}
      onPointerMove={(e) => {
        if (held !== null && onMove) onMove(held, Math.round(place(e.clientX)));
      }}
      onPointerUp={() => setHeld(null)}
      onPointerLeave={() => setHeld(null)}
    >
      <path d={CURVE} fill="none" stroke="var(--color-bc-line)" strokeWidth={3} />
      <line
        x1={W / 2}
        y1={BASE - PEAK - 6}
        x2={W / 2}
        y2={BASE + 4}
        stroke="var(--color-bc-line)"
        strokeDasharray="4 4"
      />
      <line x1={0} y1={BASE} x2={W} y2={BASE} stroke="var(--color-bc-line)" />
      {!small && (
        <>
          <text x={W / 4} y={H - 2} textAnchor="middle" className="fill-bc-subtle text-[13px] uppercase tracking-wider">
            Figuring things out
          </text>
          <text
            x={(3 * W) / 4}
            y={H - 2}
            textAnchor="middle"
            className="fill-bc-subtle text-[13px] uppercase tracking-wider"
          >
            Making it happen
          </text>
        </>
      )}
      {lists.map((l, i) => {
        const x = (l.hill / 100) * W;
        const y = yAt(x);
        return (
          <g
            key={l.id}
            className={l.color ? `bc-c-${l.color}` : ''}
            style={{ cursor: onMove ? 'grab' : 'default' }}
            onPointerDown={(e) => {
              if (!onMove) return;
              (e.target as Element).setPointerCapture?.(e.pointerId);
              setHeld(l.id);
            }}
          >
            <circle
              cx={x}
              cy={y}
              r={small ? 9 : 11}
              fill={l.color ? 'var(--c)' : FALLBACK[i % FALLBACK.length]}
              stroke="white"
              strokeWidth={3}
            >
              <title>{l.title}</title>
            </circle>
            {!small && (
              <text
                x={x + (x > W - 140 ? -16 : 16)}
                y={y - 10}
                textAnchor={x > W - 140 ? 'end' : 'start'}
                className="fill-bc-ink text-[14px] font-semibold"
              >
                {l.title}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** A project's Hill Chart on its To-dos page: the hill, Update (pick the lists,
 * drag, note, save), and the updates so far. */
export function HillPanel({ projectId, lists }: { projectId: number; lists: Item[] }) {
  const [chart, setChart] = useState<HillChart | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<number, number | null>>({});
  const [note, setNote] = useState('');
  const [history, setHistory] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    getHill(projectId).then(setChart, () => {});
  }, [projectId]);
  useEffect(load, [load]);
  if (!chart) return null;
  const tracked = new Map(chart.lists.map((l) => [l.id, l.hill]));
  const shown: HillList[] = editing
    ? lists
        .filter((l) => (draft[l.id] !== undefined ? draft[l.id] !== null : tracked.has(l.id)))
        .map((l) => ({ id: l.id, title: l.title, color: l.color, hill: draft[l.id] ?? tracked.get(l.id) ?? 0 }))
    : chart.lists;
  const save = async () => {
    try {
      const changed = Object.fromEntries(
        Object.entries(draft).filter(([id, v]) => v !== (tracked.get(Number(id)) ?? null)),
      );
      if (!Object.keys(changed).length && !note.trim()) {
        setEditing(false);
        return;
      }
      // A note alone still saves the hill as it stands.
      const positions = Object.keys(changed).length
        ? changed
        : Object.fromEntries(chart.lists.map((l) => [l.id, l.hill]));
      setChart(await setHill(projectId, positions, note));
      setEditing(false);
      setDraft({});
      setNote('');
      setError('');
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save the Hill Chart.'));
    }
  };
  if (!chart.lists.length && !editing) {
    if (!lists.length) return null;
    return (
      <p className="mt-4 text-[15px] text-bc-subtle">
        <button type="button" className="text-bc-blue underline" onClick={() => setEditing(true)}>
          Track lists on a Hill Chart
        </button>{' '}
        to show where each piece of work stands: still figuring it out, or making it happen.
      </p>
    );
  }
  return (
    <section aria-label="Hill Chart" className="mt-6 rounded-lg border border-bc-line p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-bold">Hill Chart</h2>
        {chart.updated_at && !editing && (
          <span className="text-[13px] text-bc-subtle">Updated {when(chart.updated_at)}</span>
        )}
        {!editing && (
          <button type="button" className="bc-btn bc-btn-sm ml-auto" onClick={() => setEditing(true)}>
            Update
          </button>
        )}
      </div>
      {chart.stale && !editing && (
        <p className="mt-2 rounded bg-bc-today px-3 py-1.5 text-[14px]">
          It's been a while since anyone moved this hill. Is the work still where it says?
        </p>
      )}
      <div className="mt-2">
        <Hill lists={shown} onMove={editing ? (id, hill) => setDraft((d) => ({ ...d, [id]: hill })) : undefined} />
      </div>
      {editing && (
        <div className="mt-2">
          <p className="text-[14px] text-bc-subtle">
            Drag each dot to where the work stands. Up the hill is figuring it out; down the other side is making it
            happen.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {lists.map((l) => {
              const on = draft[l.id] !== undefined ? draft[l.id] !== null : tracked.has(l.id);
              return (
                <label
                  key={l.id}
                  className="flex items-center gap-1.5 rounded-full border border-bc-line px-3 py-0.5 text-[14px]"
                >
                  <input
                    type="checkbox"
                    className="bc-checkbox"
                    checked={on}
                    onChange={(e) =>
                      setDraft((d) => ({ ...d, [l.id]: e.target.checked ? (tracked.get(l.id) ?? 0) : null }))
                    }
                  />
                  {l.title}
                </label>
              );
            })}
          </div>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            maxLength={20000}
            aria-label="Note"
            placeholder="What changed? (optional)"
            className="bc-input mt-2"
          />
          {error && (
            <p role="alert" className="mt-1 text-sm text-bc-unread">
              {error}
            </p>
          )}
          <div className="mt-2 flex gap-2">
            <button type="button" className="bc-btn bc-btn-primary" onClick={() => void save()}>
              Save the Hill Chart
            </button>
            <button
              type="button"
              className="bc-btn"
              onClick={() => {
                setEditing(false);
                setDraft({});
                setNote('');
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {chart.updates.length > 0 && !editing && (
        <div className="mt-2">
          <button type="button" className="text-[14px] text-bc-blue underline" onClick={() => setHistory((h) => !h)}>
            {history ? 'Hide the updates' : `See the updates (${chart.updates.length})`}
          </button>
          {history && (
            <ul className="mt-2 space-y-3">
              {chart.updates.map((u) => (
                <li key={u.id} className="flex gap-3 border-t border-bc-line pt-3">
                  <Avatar person={u.creator} size={28} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px]">
                      <b>{u.creator?.name ?? 'Someone'}</b> <span className="text-bc-subtle">{when(u.created_at)}</span>
                    </p>
                    {u.body && <p className="text-[15px]">{u.body}</p>}
                    <Hill lists={u.lists ?? []} small />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
