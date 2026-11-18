// Projects GTD — a project's board, where the project opens, laid out as Trello's:
// one row of lists — Triage (where new cards land), the work columns, Done — with
// Not now folded to a slim strip at the end. Trello's speed on top: a filter that
// stays set (f, x, q), label bars and date chips on each card, single keys on the
// card under the mouse (Enter or e opens, c archives, Space assigns you, d finishes,
// , and . move it left and right), ; shows label names, paste many lines to add
// many cards, columns collapse and warn past their card limit. Cards drag between
// columns on a computer; everywhere, tapping a card opens it, and its "Move along
// to…" is the move (CardSheet).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { todayStr } from '../todo-gtd/util';
import {
  addColumn,
  archiveAllCards,
  archivedCards,
  ARCHIVED_PAGE,
  cardTemplates,
  copyCard,
  createCard,
  getBoard,
  getCard,
  getProject,
  getRules,
  moveAllCards,
  moveCard,
  pressRule,
  sortColumn,
  updateCard,
  updateColumn,
  updateItem,
  type Rule,
} from './api';
import type { CardTemplate } from './api';
import { AutomationPanel } from './Automation';
import { CardTableView } from './CardTableView';
import { dropIndex, moveLocal } from './boardOps';
import { CardSheet } from './CardSheet';
import { LabelsEditor } from './LabelsEditor';
import { AddWormhole, WormholeTarget } from './Wormholes';
import { SelectionBar, toggleSelected } from './CardSelection';
import { ProjectsShell, usePeople } from './ProjectsShell';
import type { Board, Card, Column, Project } from './types';
import { AvatarStack, ColorPicker, day, dueTone, Menu, Perma, type MenuItem } from './ui';

const AGED_DAYS = 21; // Trello's Card Aging: an untouched card fades

// ── Remembered per browser: collapsed columns, the filter, label names ───────

function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (v: T) => {
      setValue(v);
      try {
        localStorage.setItem(key, JSON.stringify(v));
      } catch {
        /* private window: forget it */
      }
    },
    [key],
  );
  return [value, set];
}

export interface Filter {
  text: string;
  person: string;
  label: string;
  due: '' | 'overdue' | 'week' | 'none';
  /** Trello's "marked complete" filter; missing in a filter saved before it existed. */
  done?: '' | 'open' | 'done';
}
const NO_FILTER: Filter = { text: '', person: '', label: '', due: '', done: '' };

export function matches(card: Card, f: Filter, meId: number | undefined, today: string): boolean {
  const text = f.text.trim().toLowerCase();
  if (text && !`${card.title} ${card.notes}`.toLowerCase().includes(text)) return false;
  if (f.person === 'me' && !card.assignees?.some((a) => a.id === meId)) return false;
  if (f.person && f.person !== 'me' && !card.assignees?.some((a) => String(a.id) === f.person)) return false;
  if (f.label && !card.labels?.some((l) => String(l.id) === f.label)) return false;
  if (f.due === 'none' && card.due_date) return false;
  if (f.done === 'open' && card.completed) return false;
  if (f.done === 'done' && !card.completed) return false;
  if (f.due === 'overdue' && !(card.due_date && card.due_date < today && !card.completed)) return false;
  if (f.due === 'week') {
    const [y, m, d] = today.split('-').map(Number);
    const week = new Date(y, m - 1, d + 7);
    const end = `${week.getFullYear()}-${String(week.getMonth() + 1).padStart(2, '0')}-${String(week.getDate()).padStart(2, '0')}`;
    if (!(card.due_date && card.due_date >= today && card.due_date <= end)) return false;
  }
  return true;
}

function aged(card: Card, now = Date.now()): boolean {
  return !card.completed && now - new Date(card.updated_at).getTime() > AGED_DAYS * 86_400_000;
}

// ── A card on the table ──────────────────────────────────────────────────────

function CardTile({
  card,
  today,
  showNames,
  selected = false,
  onOpen,
  onHover,
  onDragStart,
  onDrop,
}: {
  card: Card;
  today: string;
  showNames: boolean;
  selected?: boolean;
  /** `multi`: a Shift-, Cmd- or Ctrl-click, which selects rather than opens. */
  onOpen: (multi: boolean) => void;
  onHover: (id: number | null) => void;
  onDragStart: () => void;
  onDrop: () => void;
}) {
  const steps = card.steps_count ?? 0;
  return (
    <li
      draggable
      onMouseEnter={() => onHover(card.id)}
      onMouseLeave={() => onHover(null)}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', String(card.id));
        e.dataTransfer.effectAllowed = 'move';
        onDragStart();
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onDrop();
      }}
    >
      <button
        type="button"
        onClick={(e) => onOpen(e.shiftKey || e.metaKey || e.ctrlKey)}
        aria-label={`Open card ${card.title}`}
        aria-pressed={selected || undefined}
        className={`block w-full overflow-hidden rounded-lg border bg-bc-canvas text-left text-[14px] shadow-[0_1px_1px_rgb(0_0_0/0.12)] hover:border-bc-faint ${selected ? 'border-bc-blue ring-2 ring-bc-blue' : 'border-transparent'} ${aged(card) ? 'opacity-60' : ''}`}
      >
        {card.cover && <span className={`bc-c-${card.cover} block h-2`} style={{ background: 'var(--c)' }} />}
        <span className="block px-3 py-2">
          {(card.labels?.length ?? 0) > 0 && (
            <span className="mb-1.5 flex flex-wrap gap-1">
              {card.labels!.map((l) => (
                <span
                  key={l.id}
                  title={l.name}
                  className={`bc-c-${l.color} rounded-sm text-[11px] font-semibold leading-4 text-white ${showNames ? 'px-1.5' : 'h-2 w-10'}`}
                  style={{ background: 'var(--c)' }}
                >
                  {showNames ? l.name || ' ' : ''}
                </span>
              ))}
            </span>
          )}
          <span
            className={`block break-words ${card.completed ? 'text-bc-subtle line-through decoration-bc-faint' : ''}`}
          >
            {card.title}
          </span>
          <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-bc-subtle">
            {card.due_date && (
              <span
                className={`rounded px-1.5 py-0.5 font-semibold ${dueTone(card.due_date, !!card.completed, today)}`}
              >
                🕓 {card.starts_on ? `${day(card.starts_on)} – ` : ''}
                {day(card.due_date)}
              </span>
            )}
            {card.notes && (
              <span aria-label="Has notes" title="Has notes">
                ☰
              </span>
            )}
            {(card.comments_count ?? 0) > 0 && <span title="Comments">💬 {card.comments_count}</span>}
            {steps > 0 && (
              <span
                title="Subtasks"
                className={`rounded px-1 ${card.steps_done === steps ? 'bg-[#e3fcef] font-semibold text-[#1f845a]' : ''}`}
              >
                ☑ {card.steps_done}/{steps}
              </span>
            )}
            {card.on_hold && <span className="rounded bg-bc-today px-1 font-semibold">On hold</span>}
            {card.repeat && <span title="Repeats">🔁</span>}
            {card.template && <span className="rounded bg-bc-highlight px-1 font-semibold">Template</span>}
            {(card.assignees?.length ?? 0) > 0 && (
              <span className="ml-auto">
                <AvatarStack people={card.assignees!} size={20} max={3} />
              </span>
            )}
          </span>
        </span>
      </button>
    </li>
  );
}

// ── Adding cards: Enter adds and stays open; pasting lines adds one card each ─

function AddCard({
  board,
  column,
  onAdded,
  setError,
}: {
  board: Board;
  column: Column;
  onAdded: () => Promise<unknown>;
  setError: (e: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [templates, setTemplates] = useState<CardTemplate[]>([]);
  useEffect(() => {
    if (open) cardTemplates().then(setTemplates, () => {});
  }, [open]);
  const add = async (titles: string[]) => {
    try {
      for (const t of titles) await createCard(board.id, column.id, t);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not add the card.'));
    }
    await onAdded();
  };
  // Trello's "Create from template": a copy of a template card, from any project, here.
  const fromTemplate = async (id: number) => {
    try {
      await copyCard(id, { column_id: column.id, project_id: board.id });
      setOpen(false);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not make a card from that template.'));
    }
    await onAdded();
  };
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 w-full rounded-lg px-2 py-1.5 text-left text-[14px] text-bc-subtle hover:bg-bc-line/60 hover:text-bc-ink"
      >
        + Add a card
      </button>
    );
  }
  return (
    <form
      className="mt-2"
      onSubmit={(e) => {
        e.preventDefault();
        const t = title.trim();
        if (t) {
          setTitle('');
          void add([t]);
        }
      }}
    >
      <textarea
        autoFocus
        value={title}
        rows={2}
        maxLength={500}
        aria-label={`New card in ${column.name}`}
        placeholder="Title this card… (paste several lines for several cards)"
        onChange={(e) => setTitle(e.target.value)}
        onPaste={(e) => {
          const lines = e.clipboardData
            .getData('text')
            .split(/\r?\n/)
            .map((l) => l.trim())
            .filter(Boolean);
          if (lines.length > 1) {
            e.preventDefault();
            void add(lines.slice(0, 50));
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
          if (e.key === 'Escape') {
            setOpen(false);
            setTitle('');
          }
        }}
        className="bc-input text-[14px]"
      />
      <div className="mt-1 flex gap-2">
        <button type="submit" className="bc-btn bc-btn-primary bc-btn-sm" disabled={!title.trim()}>
          Add card
        </button>
        <button
          type="button"
          className="bc-btn bc-btn-sm"
          onClick={() => {
            setOpen(false);
            setTitle('');
          }}
        >
          Done
        </button>
      </div>
      {templates.length > 0 && (
        <select
          value=""
          aria-label={`New card in ${column.name} from a template`}
          className="bc-input mt-1 py-1 text-[13px]"
          onChange={(e) => {
            if (e.target.value) void fromTemplate(Number(e.target.value));
          }}
        >
          <option value="">Or from a template…</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
              {t.board_id !== board.id ? ` (${t.board_name})` : ''}
            </option>
          ))}
        </select>
      )}
    </form>
  );
}

// ── A column ──────────────────────────────────────────────────────────────────

interface ColumnProps {
  board: Board;
  column: Column;
  color: string;
  cards: Card[];
  today: string;
  showNames: boolean;
  work: Column[];
  collapsed: boolean;
  onCollapse: () => void;
  onOpen: (card: Card, multi: boolean) => void;
  onHover: (id: number | null) => void;
  selected: number[];
  onDragStart: (card: Card) => void;
  onDrop: (columnId: number, before: number | null, onHold?: boolean) => void;
  reload: () => Promise<Board | null>;
  setError: (e: string) => void;
}

function Slim({
  label,
  count,
  color,
  onClick,
  onDrop,
}: {
  label: string;
  count: number;
  color: string;
  onClick: () => void;
  onDrop: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label} (${count}): show`}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        onDrop();
      }}
      className={`bc-c-${color} flex w-12 shrink-0 flex-col items-center gap-2 rounded-xl bg-bc-wash py-3 hover:bg-bc-line`}
      style={color ? { background: 'var(--c-fill)' } : undefined}
    >
      <span className="text-[12px] font-bold text-bc-subtle">({count})</span>
      <span className="text-[12px] font-semibold uppercase tracking-[1px] text-bc-subtle [writing-mode:vertical-rl]">
        {label}
      </span>
    </button>
  );
}

function ColumnView(p: ColumnProps) {
  const { board, column, color, cards, today, work, reload, setError } = p;
  const [over, setOver] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(column.name);
  const [panel, setPanel] = useState<'' | 'color' | 'limit' | 'move' | 'sort'>('');
  const [limit, setLimit] = useState(String(column.card_limit ?? ''));
  const index = work.findIndex((c) => c.id === column.id);
  const fixed = column.kind !== 'column';
  const act = async (write: () => Promise<unknown>, fallback: string) => {
    try {
      await write();
    } catch (e) {
      setError(apiErrorMessage(e, fallback));
    }
    await reload();
  };
  const open = cards.filter((c) => !c.on_hold);
  const held = cards.filter((c) => c.on_hold);
  const overLimit = column.card_limit != null && column.cards.length > column.card_limit;
  if (p.collapsed && !fixed) {
    return (
      <Slim
        label={column.name}
        count={column.cards.length}
        color={color}
        onClick={p.onCollapse}
        onDrop={() => p.onDrop(column.id, null)}
      />
    );
  }
  const menu: (MenuItem | 'sep')[] = [
    { label: 'Rename', onClick: () => setEditing(true) },
    { label: 'Collapse this column', onClick: p.onCollapse, hidden: column.kind === 'triage' },
    { label: 'Change the colour', onClick: () => setPanel('color'), hidden: fixed },
    {
      label: column.has_on_hold ? 'Remove the On Hold section' : 'Add an On Hold section',
      hidden: fixed,
      onClick: () =>
        void act(() => updateColumn(column.id, { has_on_hold: !column.has_on_hold }), 'Could not change On Hold.'),
    },
    { label: 'Set a card limit', onClick: () => setPanel('limit'), hidden: fixed },
    'sep',
    { label: 'Move all cards…', onClick: () => setPanel('move'), hidden: column.cards.length === 0 },
    { label: 'Sort cards…', onClick: () => setPanel('sort'), hidden: column.cards.length < 2 },
    {
      label: 'Archive all cards',
      hidden: column.cards.length === 0,
      onClick: () => {
        if (confirm(`Archive all ${column.cards.length} cards in ${column.name}? Nothing is deleted.`))
          void act(() => archiveAllCards(column.id), 'Could not archive them.');
      },
    },
    'sep',
    {
      label: 'Move left',
      hidden: fixed || index <= 0,
      onClick: () => void act(() => updateColumn(column.id, { position: index - 1 }), 'Could not move the column.'),
    },
    {
      label: 'Move right',
      hidden: fixed || index >= work.length - 1,
      onClick: () => void act(() => updateColumn(column.id, { position: index + 1 }), 'Could not move the column.'),
    },
    {
      label: 'Archive this column',
      hidden: fixed,
      danger: true,
      onClick: () =>
        void act(() => updateColumn(column.id, { status: 'archived' }), 'Move or archive its cards first.'),
    },
  ];
  return (
    <section
      aria-label={column.name}
      className={`bc-c-${color} flex max-h-[calc(100dvh-13rem)] w-[85vw] shrink-0 snap-start flex-col overflow-y-auto rounded-xl bg-bc-wash p-2 sm:w-[272px] ${over ? 'ring-2 ring-bc-blue' : ''}`}
      style={overLimit ? { background: '#fff4d6' } : color ? { background: 'var(--c-fill)' } : undefined}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        p.onDrop(column.id, null, false);
      }}
    >
      <header className="flex min-h-10 items-center gap-1.5 px-1">
        {editing ? (
          <form
            className="flex-1"
            onSubmit={(e) => {
              e.preventDefault();
              setEditing(false);
              if (name.trim() && name.trim() !== column.name)
                void act(() => updateColumn(column.id, { name: name.trim() }), 'Could not rename the column.');
            }}
          >
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={(e) => e.currentTarget.form?.requestSubmit()}
              aria-label="Column name"
              maxLength={500}
              className="bc-input py-0.5 text-[15px] font-bold"
            />
          </form>
        ) : (
          <h2 className="flex-1 truncate text-[15px] font-bold" onDoubleClick={() => setEditing(true)}>
            {column.name}
          </h2>
        )}
        <span
          className={`text-[13px] ${overLimit ? 'font-bold text-[#a54800]' : 'text-bc-subtle'}`}
          title={column.card_limit != null ? `Card limit ${column.card_limit}` : undefined}
        >
          ({column.cards.length}
          {column.card_limit != null ? `/${column.card_limit}` : ''})
        </span>
        <Menu label={`${column.name} options`} items={menu} />
      </header>
      {panel === 'color' && (
        <div className="mb-2 rounded bg-bc-canvas p-2">
          <ColorPicker
            value={column.color ?? ''}
            onChange={(c) => {
              setPanel('');
              void act(() => updateColumn(column.id, { color: c }), 'Could not change the colour.');
            }}
          />
        </div>
      )}
      {panel === 'limit' && (
        <form
          className="mb-2 flex gap-1 rounded bg-bc-canvas p-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPanel('');
            void act(
              () => updateColumn(column.id, { card_limit: limit ? Number(limit) : null }),
              'Could not set the limit.',
            );
          }}
        >
          <input
            type="number"
            min={1}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="No limit"
            aria-label="Card limit"
            className="bc-input py-1 text-[14px]"
          />
          <button type="submit" className="bc-btn bc-btn-sm">
            Set
          </button>
        </form>
      )}
      {panel === 'move' && (
        <div className="mb-2 rounded bg-bc-canvas p-2 text-[14px]">
          <p className="font-semibold">Move all {column.cards.length} cards to…</p>
          {board.columns
            .filter((c) => c.id !== column.id)
            .map((c) => (
              <button
                key={c.id}
                type="button"
                className="block w-full rounded px-2 py-1 text-left hover:bg-bc-wash"
                onClick={() => {
                  setPanel('');
                  void act(() => moveAllCards(column.id, c.id), 'Could not move the cards.');
                }}
              >
                {c.name}
              </button>
            ))}
        </div>
      )}
      {panel === 'sort' && (
        <div className="mb-2 rounded bg-bc-canvas p-2 text-[14px]">
          <p className="font-semibold">Sort these cards by…</p>
          {(
            [
              ['due', 'Due date'],
              ['created', 'Oldest first'],
              ['newest', 'Newest first'],
              ['title', 'Title (A–Z)'],
            ] as const
          ).map(([by, label]) => (
            <button
              key={by}
              type="button"
              className="block w-full rounded px-2 py-1 text-left hover:bg-bc-wash"
              onClick={() => {
                setPanel('');
                void act(() => sortColumn(column.id, by), 'Could not sort.');
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {overLimit && (
        <p className="mb-1 px-1 text-[12px] font-semibold text-[#a54800]">Over its limit of {column.card_limit}</p>
      )}
      <ul className="flex flex-col gap-2">
        {open.map((card) => (
          <CardTile
            key={card.id}
            card={card}
            today={today}
            showNames={p.showNames}
            selected={p.selected.includes(card.id)}
            onOpen={(multi) => p.onOpen(card, multi)}
            onHover={p.onHover}
            onDragStart={() => p.onDragStart(card)}
            onDrop={() => {
              setOver(false);
              p.onDrop(column.id, card.id, false);
            }}
          />
        ))}
      </ul>
      {board.status === 'active' && <AddCard board={board} column={column} onAdded={reload} setError={setError} />}
      {column.has_on_hold && (
        <div
          className="mt-3 rounded border-2 border-dashed border-bc-faint/50 p-2"
          onDragOver={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setOver(false);
            p.onDrop(column.id, null, true);
          }}
        >
          <p className="mb-1 text-[12px] font-bold uppercase tracking-wider text-bc-subtle">On hold ({held.length})</p>
          <ul className="flex flex-col gap-2">
            {held.map((card) => (
              <CardTile
                key={card.id}
                card={card}
                today={today}
                showNames={p.showNames}
                selected={p.selected.includes(card.id)}
                onOpen={(multi) => p.onOpen(card, multi)}
                onHover={p.onHover}
                onDragStart={() => p.onDragStart(card)}
                onDrop={() => {
                  setOver(false);
                  p.onDrop(column.id, card.id, true);
                }}
              />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// ── The page ──────────────────────────────────────────────────────────────────

export function BoardPage() {
  const boardId = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const { me, reload: reloadPeople, people } = usePeople();
  const [project, setProject] = useState<Project | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState('');
  const [openId, setOpenId] = useState<number | null>(null);
  const [opened, setOpened] = useState<Card | null>(null);
  const [archived, setArchived] = useState<Card[] | null>(null);
  const [labels, setLabels] = useState(false);
  const [addingHole, setAddingHole] = useState(false);
  const [selected, setSelected] = useState<number[]>([]); // Trello's multi-select (CardSelection)
  const [notNow, setNotNow] = useState(false);
  const [doneOpen, setDoneOpen] = useStored<boolean>(`bc-done-${boardId}`, true);
  const [collapsed, setCollapsed] = useStored<number[]>(`bc-collapsed-${boardId}`, []);
  const [filter, setFilter] = useStored<Filter>(`bc-filter-${boardId}`, NO_FILTER);
  const [showNames, setShowNames] = useStored<boolean>('bc-label-names', false);
  const [view, setView] = useStored<'board' | 'table'>(`bc-view-${boardId}`, 'board');
  const [automating, setAutomating] = useState(false);
  const [rules, setRules] = useState<Rule[]>([]);
  const [newColumn, setNewColumn] = useState('');
  const [addingColumn, setAddingColumn] = useState(false);
  const [moreFilters, setMoreFilters] = useState(false); // a phone shows the selects on request
  const { pathname } = useLocation();
  const dragging = useRef<number | null>(null);
  const hovered = useRef<number | null>(null);
  const filterBox = useRef<HTMLInputElement>(null);
  const today = todayStr();

  const reload = useCallback((): Promise<Board | null> => {
    return getBoard(boardId).then(
      (next) => {
        setBoard(next);
        return next;
      },
      (e) => {
        if (e instanceof ApiError && e.status === 404) setMissing(true);
        else setError(apiErrorMessage(e, 'Could not load the board.'));
        return null;
      },
    );
  }, [boardId]);
  useEffect(() => {
    void reload();
  }, [reload]);
  useEffect(() => {
    getProject(boardId).then(setProject, () => {});
  }, [boardId]);
  const loadRules = useCallback(() => {
    getRules(boardId).then(setRules, () => setRules([]));
  }, [boardId]);
  useEffect(loadRules, [loadRules]);
  // ?card=7 opens that card (links from Activity, Bookmarks and comments), an
  // archived one too: it is looked up among the archived cards.
  const [previousParams, setPreviousParams] = useState<typeof params | null>(null);
  if (params !== previousParams) {
    setPreviousParams(params);
    const card = Number(params.get('card'));
    if (card) setOpenId(card);
  }
  useEffect(() => {
    if (!board || openId === null || opened || board.columns.some((c) => c.cards.some((x) => x.id === openId))) return;
    getCard(openId).then(
      (found) => {
        if (found.board_id === board.id) setOpened(found);
      },
      () => {},
    );
  }, [board, openId, opened]);

  const act = useCallback(
    async (write: () => Promise<unknown>, fallback: string) => {
      setError('');
      try {
        await write();
      } catch (e) {
        setError(apiErrorMessage(e, fallback));
      }
      await reload();
    },
    [reload],
  );

  // Trello's single keys, on the card under the mouse; f, x, q and ; anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        t.closest('input, textarea, select, [contenteditable], [role="dialog"]') ||
        !board
      )
        return;
      const card = board.columns.flatMap((c) => c.cards).find((c) => c.id === hovered.current);
      // , and . step through the lists as drawn: Triage, the work columns, Done, then Not now.
      const kind = (k: string) => board.columns.filter((c) => (c.kind ?? 'column') === k);
      const columns = [...kind('triage'), ...kind('column'), ...kind('done'), ...kind('not_now')];
      const at = card ? columns.findIndex((c) => c.id === card.column_id) : -1;
      const key = e.key;
      if (key === 'f') {
        e.preventDefault();
        filterBox.current?.focus();
        return;
      }
      if (key === 'x') {
        setFilter(NO_FILTER);
        return;
      }
      if (key === 'Escape' && selected.length) {
        setSelected([]);
        return;
      }
      if (key === 'q') {
        setFilter({ ...filter, person: filter.person === 'me' ? '' : 'me' });
        return;
      }
      if (key === ';') {
        setShowNames(!showNames);
        return;
      }
      if (!card) return;
      if (key === 'Enter' || key === 'e') {
        e.preventDefault();
        setOpened(null);
        setOpenId(card.id);
      }
      if (key === 'c') void act(() => updateCard(card.id, { status: 'archived' }), 'Could not archive the card.');
      if (key === ' ') {
        e.preventDefault();
        const mine = card.assignees?.some((a) => a.kind === 'me');
        const ids = (card.assignees ?? []).filter((a) => a.kind !== 'me').map((a) => a.id as number | string);
        void act(() => updateCard(card.id, { assignee_ids: mine ? ids : [...ids, 'me'] }), 'Could not assign it.').then(
          reloadPeople,
        );
      }
      if (key === 'd') void act(() => updateCard(card.id, { completed: !card.completed }), 'Could not change it.');
      if ((key === ',' || key === '.') && at >= 0) {
        const next = columns[at + (key === ',' ? -1 : 1)];
        if (next) void act(() => moveCard(card.id, next.id), 'Could not move the card.');
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [board, filter, setFilter, showNames, setShowNames, act, reloadPeople, selected]);

  const drop = async (columnId: number, before: number | null, onHold?: boolean) => {
    const cardId = dragging.current;
    dragging.current = null;
    if (!board || cardId === null || cardId === before) return;
    const position = dropIndex(board, cardId, columnId, before);
    setBoard(moveLocal(board, cardId, columnId, position));
    try {
      await moveCard(cardId, columnId, position, onHold);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not move the card.'));
    }
    await reload();
  };

  const shown = useMemo(() => {
    if (!board) return new Map<number, Card[]>();
    return new Map(board.columns.map((c) => [c.id, c.cards.filter((card) => matches(card, filter, me?.id, today))]));
  }, [board, filter, me?.id, today]);

  if (missing) {
    return (
      <ProjectsShell>
        <Perma>
          <p>
            This project was not found.{' '}
            <Link to="/" className="underline">
              Back to Home
            </Link>
          </p>
        </Perma>
      </ProjectsShell>
    );
  }
  // A project whose board is switched off opens on its Overview; /cards and ?card= still reach it.
  if (
    project &&
    !project.dock.some((t) => t.tool === 'kanban_board' && t.enabled) &&
    !pathname.endsWith('/cards') &&
    !params.get('card')
  ) {
    return <Navigate to={`/p/${boardId}/overview`} replace />;
  }
  if (!board)
    return (
      <ProjectsShell>
        <Perma>
          {error && (
            <p role="alert" className="text-bc-unread">
              {error}
            </p>
          )}
        </Perma>
      </ProjectsShell>
    );

  const openCard = opened ?? board.columns.flatMap((c) => c.cards).find((c) => c.id === openId) ?? null;
  const triage = board.columns.find((c) => c.kind === 'triage');
  const later = board.columns.find((c) => c.kind === 'not_now');
  const done = board.columns.find((c) => c.kind === 'done');
  const work = board.columns.filter((c) => c.kind === 'column' || c.kind === undefined);
  const filtering = filter.text || filter.person || filter.label || filter.due || filter.done;
  const clickCard = (card: Card, multi: boolean) => {
    if (multi) {
      setSelected((s) => toggleSelected(s, card.id));
      return;
    }
    setOpened(null);
    setOpenId(card.id);
  };
  const onHover = (id: number | null) => {
    hovered.current = id;
  };
  const onDragStart = (card: Card) => {
    dragging.current = card.id;
  };
  const onDrop: ColumnProps['onDrop'] = (id, before, hold) => void drop(id, before, hold);
  const columnEvents = { onHover, onDragStart, onDrop };
  const columnProps = (column: Column, color: string): Omit<ColumnProps, keyof typeof columnEvents> => ({
    board,
    column,
    color,
    cards: shown.get(column.id) ?? [],
    today,
    showNames,
    work,
    collapsed: collapsed.includes(column.id),
    onCollapse: () =>
      setCollapsed(
        collapsed.includes(column.id) ? collapsed.filter((i) => i !== column.id) : [...collapsed, column.id],
      ),
    onOpen: clickCard,
    selected,
    reload,
    setError,
  });

  return (
    <ProjectsShell project={project} title={board.name}>
      <Perma wide>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={filterBox}
            value={filter.text}
            onChange={(e) => setFilter({ ...filter, text: e.target.value })}
            placeholder="Filter… (f)"
            aria-label="Filter cards"
            className="bc-input w-44 py-1.5 text-[14px]"
          />
          <button
            type="button"
            className="bc-btn bc-btn-sm sm:hidden"
            aria-expanded={moreFilters}
            onClick={() => setMoreFilters((m) => !m)}
          >
            Filters{filtering ? ' •' : ''}
          </button>
          <span className={`${moreFilters ? 'flex' : 'hidden'} w-full flex-wrap items-center gap-2 sm:flex sm:w-auto`}>
            <select
              value={filter.person}
              onChange={(e) => setFilter({ ...filter, person: e.target.value })}
              aria-label="Assigned to"
              className="bc-input w-auto py-1.5 text-[14px]"
            >
              <option value="">Anyone</option>
              <option value="me">My cards (q)</option>
              {people
                .filter((x) => x.kind !== 'me')
                .map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
            </select>
            {(board.labels?.length ?? 0) > 0 && (
              <select
                value={filter.label}
                onChange={(e) => setFilter({ ...filter, label: e.target.value })}
                aria-label="Label"
                className="bc-input w-auto py-1.5 text-[14px]"
              >
                <option value="">Any label</option>
                {board.labels!.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name || l.color}
                  </option>
                ))}
              </select>
            )}
            <select
              value={filter.due}
              onChange={(e) => setFilter({ ...filter, due: e.target.value as Filter['due'] })}
              aria-label="Due"
              className="bc-input w-auto py-1.5 text-[14px]"
            >
              <option value="">Any date</option>
              <option value="overdue">Overdue</option>
              <option value="week">Due in the next week</option>
              <option value="none">No due date</option>
            </select>
            <select
              value={filter.done ?? ''}
              onChange={(e) => setFilter({ ...filter, done: e.target.value as Filter['done'] })}
              aria-label="Done or not"
              className="bc-input w-auto py-1.5 text-[14px]"
            >
              <option value="">Done or not</option>
              <option value="open">Not done</option>
              <option value="done">Done</option>
            </select>
          </span>
          {filtering && (
            <button type="button" className="text-[14px] text-bc-blue underline" onClick={() => setFilter(NO_FILTER)}>
              Clear (x)
            </button>
          )}
          <span className="ml-auto">
            <Menu
              label="Board options"
              items={[
                { label: 'Labels…', onClick: () => setLabels(true) },
                { label: 'Automation…', hidden: board.status !== 'active', onClick: () => setAutomating(true) },
                {
                  label: 'Add a wormhole…',
                  hidden: board.status !== 'active' || (board.wormholes?.length ?? 0) >= 4,
                  onClick: () => setAddingHole(true),
                },
                {
                  label: view === 'board' ? 'Show as a table' : 'Show as a board',
                  onClick: () => setView(view === 'board' ? 'table' : 'board'),
                },
                {
                  label: showNames ? 'Hide label names (;)' : 'Show label names (;)',
                  onClick: () => setShowNames(!showNames),
                },
                {
                  label: `Archived cards (${board.archived_cards})`,
                  hidden: board.archived_cards === 0,
                  onClick: () => void archivedCards(board.id).then(setArchived),
                },
              ]}
            />
          </span>
        </div>
        {board.status === 'archived' && (
          <p className="mt-2 text-sm text-bc-subtle">
            This project is archived. Restore it from its page to change it.
          </p>
        )}
        {error && (
          <p role="alert" className="mt-2 text-sm text-bc-unread">
            {error}
          </p>
        )}
        {automating && (
          <AutomationPanel
            board={board}
            onClose={() => {
              setAutomating(false);
              loadRules();
              void reload();
            }}
          />
        )}
        {board.status === 'active' && rules.some((r) => r.kind === 'board_button') && (
          <div className="mt-3 flex flex-wrap gap-2" aria-label="Board buttons">
            {rules
              .filter((r) => r.kind === 'board_button')
              .map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className="bc-btn bc-btn-sm"
                  title={`For each card in ${board.columns.find((c) => c.id === r.trigger.column)?.name ?? '?'}`}
                  onClick={() => void act(() => pressRule(r.id).then(() => undefined), `Could not run “${r.name}”.`)}
                >
                  ▶ {r.name}
                </button>
              ))}
          </div>
        )}
        {view === 'table' && (
          <CardTableView
            board={board}
            cards={board.columns.flatMap((c) => shown.get(c.id) ?? [])}
            today={today}
            onOpen={(card) => {
              setOpened(null);
              setOpenId(card.id);
            }}
            reload={reload}
            setError={setError}
          />
        )}

        <div
          className={`-mx-2 mt-4 flex snap-x snap-mandatory items-start gap-3 overflow-x-auto px-2 pb-4 sm:mx-0 sm:snap-none sm:px-0 ${view === 'table' ? 'hidden' : ''}`}
        >
          {triage && <ColumnView {...columnEvents} {...columnProps(triage, '')} />}
          {work.map((column) => (
            <ColumnView key={column.id} {...columnEvents} {...columnProps(column, column.color || '')} />
          ))}
          {board.status === 'active' &&
            (addingColumn ? (
              <form
                className="w-[85vw] shrink-0 snap-start rounded-xl bg-bc-wash p-2 sm:w-[272px]"
                onSubmit={(e) => {
                  e.preventDefault();
                  const n = newColumn.trim();
                  if (n) {
                    setNewColumn('');
                    setAddingColumn(false);
                    void act(() => addColumn(board.id, n), 'Could not add the column.');
                  }
                }}
              >
                <input
                  autoFocus
                  value={newColumn}
                  onChange={(e) => setNewColumn(e.target.value)}
                  maxLength={500}
                  onBlur={() => {
                    if (!newColumn.trim()) setAddingColumn(false);
                  }}
                  placeholder="Name this column…"
                  aria-label="New column name"
                  className="bc-input text-[14px]"
                />
              </form>
            ) : (
              <button
                type="button"
                onClick={() => setAddingColumn(true)}
                className="w-[85vw] shrink-0 snap-start rounded-xl bg-bc-wash/70 px-3 py-2.5 text-left text-[14px] font-semibold text-bc-subtle hover:bg-bc-wash hover:text-bc-ink sm:w-[272px]"
              >
                + Add a column
              </button>
            ))}
          {done &&
            (doneOpen ? (
              <ColumnView {...columnEvents} {...columnProps(done, '')} onCollapse={() => setDoneOpen(false)} />
            ) : (
              <Slim
                label={done.name}
                count={done.cards.length}
                color=""
                onClick={() => setDoneOpen(true)}
                onDrop={() => void drop(done.id, null, false)}
              />
            ))}
          {later &&
            (notNow ? (
              <ColumnView {...columnEvents} {...columnProps(later, '')} onCollapse={() => setNotNow(false)} />
            ) : (
              <Slim
                label={later.name}
                count={later.cards.length}
                color=""
                onClick={() => setNotNow(true)}
                onDrop={() => void drop(later.id, null, false)}
              />
            ))}
          {board.wormholes?.map((hole) => (
            <WormholeTarget
              key={hole.id}
              hole={hole}
              onDrop={() => {
                const id = dragging.current;
                dragging.current = null;
                if (id !== null) void act(() => moveCard(id, hole.column_id), 'Could not send the card.');
              }}
              onClose={() =>
                void act(() => updateItem(hole.id, { status: 'archived' }), 'Could not close the wormhole.')
              }
            />
          ))}
        </div>

        {selected.length > 0 && (
          <SelectionBar board={board} selected={selected} act={act} onClear={() => setSelected([])} />
        )}
        {addingHole && (
          <AddWormhole
            boardId={board.id}
            onDone={() => {
              setAddingHole(false);
              void reload();
            }}
          />
        )}

        {labels && (
          <LabelsEditor
            boardId={board.id}
            onClose={() => {
              setLabels(false);
              void reload();
            }}
          />
        )}

        {archived && (
          <section className="mt-4 max-w-xl">
            <h2 className="text-sm font-bold">Archived cards</h2>
            <ul className="mt-2 space-y-1">
              {archived.map((card) => (
                <li key={card.id} className="flex items-center gap-3 text-sm">
                  <button
                    type="button"
                    className="text-left hover:underline"
                    onClick={() => {
                      setOpened(card);
                      setOpenId(card.id);
                    }}
                  >
                    {card.title}
                  </button>
                  <button
                    type="button"
                    className="text-bc-blue underline"
                    onClick={() =>
                      void act(async () => {
                        await updateCard(card.id, { status: 'active' });
                        setArchived(await archivedCards(board.id));
                      }, 'Could not restore the card.')
                    }
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
            {archived.length > 0 && archived.length % ARCHIVED_PAGE === 0 && (
              <button
                type="button"
                className="mt-2 text-sm text-bc-subtle underline"
                onClick={() =>
                  void archivedCards(board.id, archived.length).then((more) => setArchived([...archived, ...more]))
                }
              >
                Show more
              </button>
            )}
          </section>
        )}

        {openCard && (
          <CardSheet
            key={openCard.id}
            card={openCard}
            board={board}
            reload={reload}
            buttons={rules.filter((r) => r.kind === 'card_button')}
            onClose={() => {
              setOpenId(null);
              setOpened(null);
              if (params.get('card')) setParams({}, { replace: true });
              if (archived) void archivedCards(board.id).then(setArchived);
            }}
          />
        )}
      </Perma>
    </ProjectsShell>
  );
}
