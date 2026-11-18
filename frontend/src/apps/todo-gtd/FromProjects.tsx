// Projects GTD work assigned to the person, on Todo's To Do page: the "From Projects
// GTD" group. It lists their open to-dos and cards there, each with its project and
// due date. Nothing is copied into Todo: a check here is the write Projects GTD
// itself makes, and work assigned to an AI or to someone else stays over there.
//
// A checked row stays in place, struck through, with its own Undo, until the page
// reloads. It does not use Todo's undo queue (undoQueue.ts), which goes by to-do id:
// a Projects GTD to-do or card can carry the number of one of Todo's.
import { useCallback, useEffect, useState } from 'react';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { CARD_CHANGED, completeItem, getAssignments, moveCard, updateCard } from '../projects-gtd/api';
import type { Card, Item } from '../projects-gtd/types';
import { Logo } from './components/Logo';
import { useCrossAppHref } from './hop';
import { useSession } from './session';
import { useListTz } from './useTodoMeta';
import { dueLabel, todayStr } from './util';

interface Row {
  /** 't7' or 'c7': to-dos and cards number separately. */
  key: string;
  id: number;
  title: string;
  project: string;
  due: string | null;
  repeat: boolean;
  /** Its own page in Projects GTD, under that app's /app. */
  path: string;
  /** A card as last read while open: the version its completion names, and the column
   *  and On Hold that Undo puts back. Null for a to-do. */
  card: Card | null;
  done: boolean;
  /** A completed card's version, as the completion answered: Undo's move names it. */
  doneVersion?: number;
  busy: boolean;
  error: string;
}

function toRows({ todos, cards }: { todos: Item[]; cards: Card[] }): Row[] {
  const open = { done: false, busy: false, error: '' };
  return [
    ...todos.map((t) => ({
      ...open,
      key: `t${t.id}`,
      id: t.id,
      title: t.title,
      project: t.board_name,
      due: t.due_on,
      repeat: !!t.repeat,
      path: `/i/${t.id}`,
      card: null,
    })),
    ...cards.map((c) => ({
      ...open,
      key: `c${c.id}`,
      id: c.id,
      title: c.title,
      project: c.board_name,
      due: c.due_date,
      repeat: !!c.repeat,
      path: `/p/${c.board_id}/cards?card=${c.id}`,
      card: c,
    })),
    // Soonest due first, the undated last: '9' sorts after any date.
  ].sort((a, b) => (a.due ?? '9').localeCompare(b.due ?? '9'));
}

/** The group, or nothing: with Projects GTD off, with nothing assigned, and while one
 *  of the page's context or people filters is on (`facets`), which none of these rows
 *  can match. `search` is the page's filter text, matched on title and project. */
export function FromProjects({ search, facets }: { search: string; facets: boolean }) {
  const on = useSession().session?.apps.includes('projects') ?? false;
  const [rows, setRows] = useState<Row[]>([]);
  const [note, setNote] = useState('');
  const href = useCrossAppHref('projects');
  const today = todayStr(new Date(), useListTz());

  // An extra: when it cannot be read, the page shows without it.
  const load = useCallback(
    () =>
      getAssignments().then(
        (mine) => setRows(toRows(mine)),
        () => {},
      ),
    [],
  );
  useEffect(() => {
    if (on) void load();
  }, [on, load]);

  const patch = (key: string, change: Partial<Row>) =>
    setRows((all) => all.map((r) => (r.key === key ? { ...r, ...change } : r)));

  /** One write for a row; `call` answers what the row becomes. A card that changed
   *  since it was read (409) is left alone: the group says so and shows the latest.
   *  Any other failure leaves the row as it was, with the reason under it. */
  const write = async (row: Row, call: () => Promise<Partial<Row>>, fallback: string) => {
    patch(row.key, { busy: true, error: '' });
    setNote('');
    try {
      patch(row.key, { busy: false, ...(await call()) });
    } catch (e) {
      const changed = row.card !== null && e instanceof ApiError && e.status === 409;
      patch(row.key, { busy: false, error: changed ? '' : apiErrorMessage(e, fallback) });
      if (changed) {
        setNote(CARD_CHANGED);
        void load();
      }
    }
  };

  const complete = (row: Row) =>
    write(
      row,
      async () => {
        if (!row.card) {
          await completeItem(row.id, true);
          return { done: true };
        }
        const done = await updateCard(row.id, { completed: true, version: row.card.version });
        return { done: true, doneVersion: done.version };
      },
      'Could not check it off. Try again.',
    );

  const undo = (row: Row) =>
    write(
      row,
      async () => {
        if (!row.card) {
          await completeItem(row.id, false);
          return { done: false };
        }
        // Completing took the card to Done and off hold, and re-opening one sends it to
        // the first work column. So Undo is one move: back to the column it was read
        // in, on hold if it was, refused if the card has changed since it was completed.
        // simplification: it goes to the bottom of that column, not back to its place there; the way up is to remember its position and send it with the move.
        const back = await moveCard(row.id, row.card.column_id, undefined, !!row.card.on_hold, row.doneVersion);
        return { done: false, card: back };
      },
      'Could not undo it. Try again.',
    );

  const q = search.trim().toLowerCase();
  const shown = rows.filter((r) => !q || `${r.title}\n${r.project}`.toLowerCase().includes(q));
  if (!on || facets || (shown.length === 0 && !note)) return null;

  return (
    <section aria-label="From Projects GTD">
      <h2 className="mb-2 flex items-center gap-1.5 text-xs font-heading font-bold uppercase tracking-wide text-projects-ink">
        <Logo app="projects" className="h-4 w-4" />
        From Projects GTD
      </h2>
      {note && (
        <p role="alert" className="mb-2 text-sm text-red-600 dark:text-red-400">
          {note}
        </p>
      )}
      <div className="space-y-2">
        {shown.map((row) => {
          const link = href(row.path);
          const due = row.due ? dueLabel(row.due, today) : null;
          return (
            <div
              key={row.key}
              className="flex items-start gap-3 rounded-xl border border-line-faint bg-cream px-3 py-2.5"
            >
              <input
                type="checkbox"
                checked={row.done}
                disabled={row.busy}
                onChange={() => void (row.done ? undo(row) : complete(row))}
                className="mt-1 h-5 w-5 shrink-0 cursor-pointer accent-[#27ae60]"
                aria-label={row.done ? 'Mark not done' : 'Mark done'}
              />
              <div className="min-w-0 flex-1">
                <p className={`text-sm break-words ${row.done ? 'text-muted line-through' : 'text-charcoal'}`}>
                  {link ? (
                    <a href={link} className="hover:underline">
                      {row.title}
                    </a>
                  ) : (
                    row.title
                  )}
                  {row.repeat && (
                    <span
                      role="img"
                      className="ml-1 text-blue-700 dark:text-blue-300"
                      title="Repeats"
                      aria-label="Repeats"
                    >
                      ↻
                    </span>
                  )}
                </p>
                <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
                  {due && (
                    <span className={due.overdue && !row.done ? 'font-bold text-brand-ink' : 'text-muted'}>
                      {due.text}
                    </span>
                  )}
                  <span className="rounded-full bg-sand px-2 py-0.5 text-muted">{row.project}</span>
                </p>
                {row.error && (
                  <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
                    {row.error}
                  </p>
                )}
              </div>
              {row.done && (
                <button
                  type="button"
                  disabled={row.busy}
                  onClick={() => void undo(row)}
                  className="shrink-0 rounded-lg border border-line-faint px-2 py-1 text-xs font-heading font-semibold text-charcoal hover:border-brand/40 disabled:opacity-40"
                >
                  Undo
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
