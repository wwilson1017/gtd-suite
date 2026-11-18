// Projects GTD — one card, opened: edit it, move it (the phone's way, and the
// keyboard's), archive it. Each field saves on its own, naming the version it
// was read at, so a save never overwrites what an agent wrote meanwhile (409).
import { useEffect, useId, useRef, useState } from 'react';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { formatAge } from '../todo-gtd/util';
import {
  boostCard,
  boostItem,
  CARD_CHANGED,
  cardThread,
  commentOnCard,
  completeItem,
  copyCard,
  createCard,
  createItem,
  listBoards,
  moveCard,
  moveCardToProject,
  removeBoost,
  updateCard,
  updateItem,
} from './api';
import { REPEATS } from './CalendarPage';
import { pressRule, type Rule } from './api';
import { usePeople } from './ProjectsShell';
import { pastedTodos } from './TodosPage';
import type { Board, BoardSummary, Boost, Card, Item, Position } from './types';
import { Avatar, Boosts, ColorPicker, Comments } from './ui';
import type { CardFields } from './api';

/** Trello's card back extras: copy the card, move it to another project, make it
 *  a template (and new cards from one). */
function CardTools({
  card,
  board,
  onChanged,
  onGone,
}: {
  card: Card;
  board: Board;
  onChanged: (note: string) => void;
  onGone: () => void;
}) {
  const [projects, setProjects] = useState<BoardSummary[] | null>(null);
  const [to, setTo] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const fail = (e: unknown) => setError(apiErrorMessage(e, 'That did not work.'));
  return (
    <details
      className="mt-4"
      onToggle={(e) => {
        if ((e.target as HTMLDetailsElement).open && !projects) listBoards().then(setProjects, () => setProjects([]));
      }}
    >
      <summary className="cursor-pointer text-xs font-heading font-semibold text-bc-subtle">
        Copy, move to another project, template
      </summary>
      <div className="mt-2 space-y-3 text-[14px]">
        {card.template ? (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void copyCard(card.id, { title: title.trim() || undefined }).then(() => {
                setTitle('');
                onChanged('Made a new card from this template.');
              }, fail);
            }}
          >
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="The new card's title"
              aria-label="New card title"
              maxLength={500}
              className={`${fieldCls} max-w-xs`}
            />
            <button type="submit" className={`${chipCls} border-bc-blue bg-bc-blue text-white`}>
              Make a card from this template
            </button>
          </form>
        ) : (
          <button
            type="button"
            className={`${chipCls} border-bc-line bg-bc-canvas text-bc-ink`}
            onClick={() =>
              void copyCard(card.id).then(() => onChanged('Copied: the copy is in the same column.'), fail)
            }
          >
            Copy this card
          </button>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={to}
            onChange={(e) => setTo(e.target.value)}
            aria-label="Move to project"
            className={`${fieldCls} max-w-xs`}
          >
            <option value="">Move to another project…</option>
            {(projects ?? [])
              .filter((p) => p.id !== board.id)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
          <button
            type="button"
            disabled={!to}
            className={`${chipCls} border-bc-line bg-bc-canvas text-bc-ink`}
            onClick={() => void moveCardToProject(card.id, Number(to)).then(onGone, fail)}
          >
            Move it (to its Triage)
          </button>
        </div>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            className="bc-checkbox"
            checked={!!card.template}
            onChange={(e) =>
              void updateCard(card.id, { template: e.target.checked, version: card.version }).then(
                () =>
                  onChanged(e.target.checked ? 'This card is a template now.' : 'This card is no longer a template.'),
                fail,
              )
            }
          />
          Card template: a starting point for new cards like it
        </label>
        {error && (
          <p role="alert" className="text-sm text-bc-unread">
            {error}
          </p>
        )}
      </div>
    </details>
  );
}

const HIDE_KEY = 'bc-hide-checked';
const hiddenChecked = () => {
  try {
    return localStorage.getItem(HIDE_KEY) === '1';
  } catch {
    return false;
  }
};

/** A card's subtasks (Trello's checklist handling: a progress bar, hide checked items,
 * paste several at once, make one a card of its own), boosts and comments. */
function CardThread({ card, position, onCardsChanged }: { card: Card; position: number; onCardsChanged: () => void }) {
  const cardId = card.id,
    boardId = card.board_id;
  const [thread, setThread] = useState<{ comments: Item[]; subtasks: Item[]; boosts: Boost[] } | null>(null);
  const [step, setStep] = useState('');
  const [hide, setHide] = useState(hiddenChecked);
  const [error, setError] = useState('');
  const { me, reload: reloadPeople } = usePeople();
  const load = () => {
    cardThread(cardId).then(setThread, () => {});
  };
  useEffect(load, [cardId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!thread) return null;
  const addSteps = async (titles: string[]) => {
    try {
      for (const title of titles)
        await createItem(boardId, 'step', { title: title.slice(0, 500) }, { card_id: cardId });
      setStep('');
      setError('');
    } catch (e) {
      setError(apiErrorMessage(e, 'Not all of them were added.'));
    }
    load();
  };
  // Trello's "Convert to card": a card just below this one, with the subtask's people and date;
  // the subtask is archived. simplification: three writes, not one transaction; a failure
  // midway leaves both, which shows and is undone by hand.
  const toCard = async (s: Item) => {
    try {
      const made = await createCard(boardId, card.column_id, s.title, position + 1);
      const ids = (s.assignees ?? []).map((p) => p.id);
      // In the same section too: below a held card is On Hold.
      const extra = {
        ...(s.due_on ? { due_date: s.due_on } : {}),
        ...(ids.length ? { assignee_ids: ids } : {}),
        ...(card.on_hold ? { on_hold: true } : {}),
      };
      if (Object.keys(extra).length) await updateCard(made.id, extra);
      await updateItem(s.id, { status: 'archived' });
      setError('');
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not make it a card.'));
    }
    load();
    onCardsChanged();
  };
  const toggleHide = () => {
    setHide(!hide);
    try {
      localStorage.setItem(HIDE_KEY, hide ? '0' : '1');
    } catch {
      /* fine: a private window remembers nothing */
    }
  };
  const done = thread.subtasks.filter((s) => s.completed).length;
  const total = thread.subtasks.length;
  const shown = hide ? thread.subtasks.filter((s) => !s.completed) : thread.subtasks;
  return (
    <div className="mt-4">
      <div className="flex items-center gap-2">
        <p className="text-xs font-semibold text-bc-subtle">Subtasks</p>
        {done > 0 && (
          <button type="button" onClick={toggleHide} className="ml-auto text-xs text-bc-blue underline">
            {hide ? `Show checked items (${done})` : 'Hide checked items'}
          </button>
        )}
      </div>
      {total > 0 && (
        <div className="mt-1 flex items-center gap-2" aria-label={`${done} of ${total} subtasks done`}>
          <span className="w-8 text-right text-xs text-bc-subtle">{Math.round((100 * done) / total)}%</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded bg-bc-wash">
            <span
              className={`block h-full ${done === total ? 'bg-[#1f845a]' : 'bg-bc-blue'}`}
              style={{ width: `${(100 * done) / total}%` }}
            />
          </span>
        </div>
      )}
      <ul className="mt-1 space-y-1">
        {shown.map((s) => (
          <li key={s.id} className="group flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="bc-checkbox"
              checked={s.completed}
              aria-label={`Subtask ${s.title}`}
              onChange={() => void completeItem(s.id, !s.completed).then(load)}
            />
            <span className={`flex-1 ${s.completed ? 'text-bc-subtle line-through' : ''}`}>{s.title}</span>
            {card.status !== 'archived' && (
              <button
                type="button"
                onClick={() => void toCard(s)}
                aria-label={`Make "${s.title}" a card`}
                className="hidden text-xs text-bc-blue underline group-hover:inline group-focus-within:inline"
              >
                Make it a card
              </button>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="text-sm text-bc-unread">
          {error}
        </p>
      )}
      <form
        className="mb-4 mt-1.5 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (step.trim()) void addSteps([step.trim()]);
        }}
      >
        <input
          value={step}
          onChange={(e) => setStep(e.target.value)}
          placeholder="Add a subtask… (paste a list to add several)"
          aria-label="New subtask"
          maxLength={500}
          className="bc-input py-1 text-sm"
          onPaste={(e) => {
            const lines = pastedTodos(e.clipboardData.getData('text'));
            if (lines.length < 2 || !confirm(`Add ${lines.length} subtasks, one for each line?`)) return;
            e.preventDefault();
            void addSteps(lines);
          }}
        />
        <button type="submit" className="bc-btn bc-btn-sm" disabled={!step.trim()}>
          Add
        </button>
      </form>
      <Boosts
        boosts={thread.boosts}
        onBoost={(c) => boostCard(cardId, c).then(load)}
        onRemove={(b) => removeBoost(b).then(load)}
      />
      <Comments
        comments={thread.comments}
        me={me}
        onAdd={(t) =>
          commentOnCard(cardId, t).then(() => {
            reloadPeople();
            load();
          })
        }
        onBoost={(cid, c) => boostItem(cid, c).then(load)}
        onRemoveBoost={(b) => removeBoost(b).then(load)}
      />
    </div>
  );
}

const fieldCls =
  'w-full rounded-lg border border-bc-line bg-bc-wash px-3 py-2 text-base sm:text-sm text-bc-ink focus:border-bc-blue focus:outline-none';
const chipCls = 'rounded-lg border px-3 py-1.5 text-sm font-heading disabled:opacity-40';

interface Props {
  card: Card;
  board: Board;
  onClose: () => void;
  /** Reload the board; resolves to it (or null when that failed). */
  reload: () => Promise<Board | null>;
  /** The project's card buttons (automation.py): pressing one acts on this card. */
  buttons?: Rule[];
}

/** Who the card is for: people as chips, a select to add someone. */
function Assignees({
  card,
  disabled,
  onSave,
}: {
  card: Card;
  disabled: boolean;
  onSave: (ids: (number | string)[]) => void;
}) {
  const { people } = usePeople();
  const on = card.assignees ?? [];
  const ids = on.map((a) => a.id as number | string);
  return (
    <div className="mt-4">
      <p className="text-xs font-heading font-semibold text-bc-subtle">Assigned to</p>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        {on.map((a) => (
          <span
            key={a.id}
            className="inline-flex items-center gap-1 rounded-full bg-bc-wash py-0.5 pl-0.5 pr-2 text-sm"
          >
            <Avatar person={a} size={20} />
            {a.name}
            {!disabled && (
              <button
                type="button"
                aria-label={`Unassign ${a.name}`}
                className="text-bc-faint hover:text-bc-ink"
                onClick={() => onSave(ids.filter((i) => i !== a.id))}
              >
                ×
              </button>
            )}
          </span>
        ))}
        {!disabled && (
          <select
            value=""
            aria-label="Assign someone"
            className="rounded-lg border border-bc-line bg-bc-canvas px-2 py-1 text-sm"
            onChange={(e) => {
              if (e.target.value) onSave([...ids, e.target.value === 'me' ? 'me' : Number(e.target.value)]);
            }}
          >
            <option value="">{on.length ? 'Add someone…' : 'Assign someone…'}</option>
            {people.length === 0 && <option value="me">Me</option>}
            {people
              .filter((p) => !ids.includes(p.id))
              .map((p) => (
                <option key={p.id} value={p.kind === 'me' ? 'me' : p.id}>
                  {p.name}
                  {p.kind === 'ai' ? ' (AI)' : ''}
                </option>
              ))}
          </select>
        )}
      </div>
    </div>
  );
}

/** The project's labels as toggles; typing a new name makes a new label. */
function Labels({
  card,
  board,
  disabled,
  onSave,
}: {
  card: Card;
  board: Board;
  disabled: boolean;
  onSave: (ids: (number | string)[]) => void;
}) {
  const [name, setName] = useState('');
  const on = (card.labels ?? []).map((l) => l.id);
  const all = board.labels ?? [];
  return (
    <div className="mt-4">
      <p className="text-xs font-heading font-semibold text-bc-subtle">Labels</p>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        {all.map((l) => (
          <button
            key={l.id}
            type="button"
            disabled={disabled}
            aria-pressed={on.includes(l.id)}
            onClick={() => onSave(on.includes(l.id) ? on.filter((i) => i !== l.id) : [...on, l.id])}
            className={`bc-c-${l.color} rounded px-2 py-0.5 text-sm font-semibold ${on.includes(l.id) ? 'text-white ring-2 ring-bc-ink' : 'text-white opacity-50'}`}
            style={{ background: 'var(--c)' }}
          >
            {l.name || l.color}
          </button>
        ))}
        {!disabled && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) {
                onSave([...on, name.trim()]);
                setName('');
              }
            }}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="+ New label"
              aria-label="New label"
              maxLength={100}
              className="w-28 rounded-lg border border-bc-line bg-bc-canvas px-2 py-0.5 text-sm"
            />
          </form>
        )}
      </div>
    </div>
  );
}

export function CardSheet({ card: opened, board, onClose, reload, buttons = [] }: Props) {
  const [card, setCard] = useState(opened);
  const [title, setTitle] = useState(opened.title);
  const [notes, setNotes] = useState(opened.notes);
  const [note, setNote] = useState('');
  const titleId = useId();
  const notesId = useId();
  const dueId = useId();
  const archived = card.status === 'archived';
  // Saves run one at a time, each naming the version the last one returned, so two
  // quick edits here never refuse each other as "changed elsewhere". Nothing is
  // disabled while one is out: leaving the notes for a Move chip starts a save, and
  // a chip disabled by it would swallow the tap. The tap queues behind the save.
  // `server` is the card as the last answer had it, whatever render queued the write.
  const server = useRef(opened);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  // Bumped by a failed write: saves still queued behind it are dropped, so none of
  // them overwrites the change that caused a refusal, or archives and closes the
  // sheet over a draft that did not save.
  const generation = useRef(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  /** Take what the server holds now: after a write, or (`all`) after a refused one.
   *  After a write, a field that differs from the last answer is a draft and stays;
   *  one that matches it takes the new text, which may be an AI's edit. */
  const adopt = (next: Card, all = false) => {
    const last = server.current;
    server.current = next;
    setCard(next);
    setTitle((t) => (all || t === last.title ? next.title : t));
    setNotes((n) => (all || n === last.notes ? next.notes : n));
  };

  /** Queued behind any write still out; resolves to whether this one was taken. */
  const run = (write: () => Promise<Card>): Promise<boolean> => {
    const mine = generation.current;
    const job = queue.current.then(() => (mine === generation.current ? attempt(write) : false));
    queue.current = job;
    return job;
  };

  const attempt = async (write: () => Promise<Card>): Promise<boolean> => {
    setNote('');
    try {
      adopt(await write());
      await reload();
      return true;
    } catch (e) {
      generation.current += 1;
      if (e instanceof ApiError && e.status === 409) {
        const fresh = (await reload())?.columns.flatMap((c) => c.cards).find((c) => c.id === card.id);
        if (fresh) adopt(fresh, true);
        setNote(CARD_CHANGED);
      } else {
        setNote(apiErrorMessage(e, 'Could not save. Try again.'));
      }
      return false;
    }
  };

  const save = (fields: CardFields) => run(() => updateCard(card.id, { ...fields, version: server.current.version }));
  const move = (columnId: number, position?: Position) => run(() => moveCard(card.id, columnId, position));

  const column = board.columns.find((c) => c.id === card.column_id);
  const index = column?.cards.findIndex((c) => c.id === card.id) ?? -1;
  const by = card.source === 'agent' ? card.source_client || 'an AI tool' : 'you';
  const age = formatAge(card.created_at);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-bc-canvas p-4 text-bc-ink shadow-xl sm:max-w-2xl sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {card.cover && (
          <div className={`bc-c-${card.cover} -mx-4 -mt-4 mb-3 h-8 rounded-t-2xl`} style={{ background: 'var(--c)' }} />
        )}
        <div className="flex items-start gap-2">
          {!archived && (
            <input
              type="checkbox"
              className="bc-checkbox mt-2.5"
              checked={!!card.completed}
              aria-label={card.completed ? 'Completed: re-open it' : 'Mark complete (moves it to Done)'}
              onChange={() => void save({ completed: !card.completed })}
            />
          )}
          <label htmlFor={titleId} className="sr-only">
            Title
          </label>
          <input
            id={titleId}
            value={title}
            maxLength={500}
            disabled={archived}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => {
              if (title.trim() && title !== card.title) void save({ title: title.trim() });
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.currentTarget.blur();
            }}
            className="min-w-0 flex-1 rounded-lg bg-transparent px-1 py-1 font-heading text-lg font-bold text-bc-ink focus:bg-bc-wash focus:outline-none"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg px-2 py-1 text-xl leading-none text-bc-subtle hover:text-bc-ink"
          >
            &times;
          </button>
        </div>
        <p className="px-1 text-xs text-bc-subtle">
          {archived ? 'Archived' : `In ${card.column_name}`} &middot; added by {by}{' '}
          {age === 'today' ? 'today' : `${age} ago`}
        </p>

        {!archived && (
          <div className="mt-4">
            <p className="text-xs font-heading font-semibold text-bc-subtle">Move along to…</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {board.columns.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  disabled={c.id === card.column_id}
                  onClick={() => void move(c.id)}
                  className={`${chipCls} ${
                    c.id === card.column_id
                      ? 'border-bc-blue bg-bc-wash text-bc-ink'
                      : 'border-bc-line bg-bc-canvas text-bc-ink hover:bg-bc-wash'
                  }`}
                >
                  {c.name}
                </button>
              ))}
              {/* Through a wormhole: to a column of another project; the card leaves this table. */}
              {board.wormholes?.map((w) => (
                <button
                  key={`w${w.id}`}
                  type="button"
                  onClick={() =>
                    void move(w.column_id).then((ok) => {
                      if (ok) onClose();
                    })
                  }
                  className={`${chipCls} border-dashed border-bc-line bg-bc-canvas text-bc-ink hover:bg-bc-wash`}
                >
                  🌀 {w.project_name} › {w.column_name}
                </button>
              ))}
            </div>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                disabled={index <= 0}
                onClick={() => void move(card.column_id, 'top')}
                className={`${chipCls} border-bc-line bg-bc-canvas text-bc-ink`}
              >
                To the top
              </button>
              <button
                type="button"
                disabled={index < 0 || index >= (column?.cards.length ?? 0) - 1}
                onClick={() => void move(card.column_id, 'bottom')}
                className={`${chipCls} border-bc-line bg-bc-canvas text-bc-ink`}
              >
                To the bottom
              </button>
              {column?.has_on_hold && (
                <button
                  type="button"
                  onClick={() => void save({ on_hold: !card.on_hold })}
                  aria-pressed={!!card.on_hold}
                  className={`${chipCls} ${card.on_hold ? 'border-bc-blue bg-bc-today' : 'border-bc-line bg-bc-canvas'} text-bc-ink`}
                >
                  {card.on_hold ? 'On hold: take it off' : 'Put on hold'}
                </button>
              )}
            </div>
          </div>
        )}

        {!archived && buttons.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2" aria-label="Card buttons">
            {buttons.map((b) => (
              <button
                key={b.id}
                type="button"
                className={`${chipCls} border-bc-blue bg-bc-canvas text-bc-ink hover:bg-bc-wash`}
                onClick={() =>
                  void run(async () => {
                    await pressRule(b.id, card.id);
                    const fresh = (await reload())?.columns.flatMap((c) => c.cards).find((c) => c.id === card.id);
                    return fresh ?? card;
                  })
                }
              >
                ▶ {b.name}
              </button>
            ))}
          </div>
        )}

        <Assignees card={card} disabled={archived} onSave={(ids) => void save({ assignee_ids: ids })} />

        <div className="mt-4 flex flex-wrap gap-4">
          <div>
            <label htmlFor={`${dueId}-start`} className="block text-xs font-heading font-semibold text-bc-subtle">
              Starts
            </label>
            <input
              id={`${dueId}-start`}
              type="date"
              value={card.starts_on ?? ''}
              disabled={archived}
              onChange={(e) => void save({ starts_on: e.target.value || null })}
              className={`${fieldCls} mt-1 max-w-[12rem]`}
            />
          </div>
          <div>
            <label htmlFor={dueId} className="block text-xs font-heading font-semibold text-bc-subtle">
              Due
            </label>
            <input
              id={dueId}
              type="date"
              value={card.due_date ?? ''}
              disabled={archived}
              onChange={(e) => void save({ due_date: e.target.value || null })}
              className={`${fieldCls} mt-1 max-w-[12rem]`}
            />
          </div>
        </div>

        {!archived && (
          <div className="mt-4">
            <label className="block text-xs font-heading font-semibold text-bc-subtle">
              Repeats
              <select
                value={card.repeat ?? ''}
                onChange={(e) => void save({ repeat: e.target.value || null })}
                className={`${fieldCls} mt-1 max-w-[14rem]`}
              >
                {REPEATS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            {card.repeat && (
              <p className="mt-1 text-xs text-bc-subtle">Finishing it adds the next one where it is now.</p>
            )}
          </div>
        )}

        <Labels card={card} board={board} disabled={archived} onSave={(ids) => void save({ labels: ids })} />

        {!archived && (
          <details className="mt-4">
            <summary className="cursor-pointer text-xs font-heading font-semibold text-bc-subtle">Cover colour</summary>
            <div className="mt-2">
              <ColorPicker value={card.cover ?? ''} onChange={(c) => void save({ cover: c })} />
            </div>
          </details>
        )}

        <label htmlFor={notesId} className="mt-4 block text-xs font-heading font-semibold text-bc-subtle">
          Notes
        </label>
        <textarea
          id={notesId}
          value={notes}
          rows={8}
          maxLength={20000}
          disabled={archived}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => {
            if (notes !== card.notes) void save({ notes });
          }}
          placeholder="Details, links, the plan. Your AI adds its updates here too."
          className={`${fieldCls} mt-1 font-mono text-[13px] leading-relaxed`}
        />

        {note && (
          <p role="alert" className="mt-2 text-sm text-bc-unread">
            {note}
          </p>
        )}

        {!archived && (
          <CardTools
            card={card}
            board={board}
            onGone={() => {
              void reload();
              onClose();
            }}
            onChanged={(msg) => {
              setNote(msg);
              void reload().then((b) => {
                const fresh = b?.columns.flatMap((c) => c.cards).find((c) => c.id === card.id);
                if (fresh) adopt(fresh, true);
              });
            }}
          />
        )}

        <CardThread card={card} position={index} onCardsChanged={reload} />

        <div className="mt-4 flex justify-between">
          <button
            type="button"
            onClick={() =>
              void save({ status: archived ? 'active' : 'archived' }).then((ok) => {
                if (ok && !archived) onClose();
              })
            }
            className={`${chipCls} border-bc-line bg-bc-canvas text-bc-subtle hover:text-bc-ink`}
          >
            {archived ? 'Restore card' : 'Archive card'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className={`${chipCls} border-transparent bg-bc-blue text-white hover:opacity-90`}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
