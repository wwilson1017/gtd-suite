// Projects GTD — the pieces every Basecamp-style page shares: avatars, the white
// panel and its breadcrumb row, the ••• menu, boosts, comments and the composer.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { Markdown } from '../notes-gtd/Markdown';
import type { Boost, Item, Person, Project, Tool } from './types';

// ── Dates ─────────────────────────────────────────────────────────────────────

/** "3:18pm" today, "May 25" this year, "May 25, 2025" before. */
export function when(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(' ', '').toLowerCase();
  }
  return d.toLocaleDateString(
    'en-US',
    d.getFullYear() === now.getFullYear()
      ? { month: 'short', day: 'numeric' }
      : { month: 'short', day: 'numeric', year: 'numeric' },
  );
}

/** "today at 3:18pm", or "on May 25": after a name, as Basecamp's bylines read. */
export function on(iso: string, now: Date = new Date()): string {
  const text = when(iso, now);
  return /\d(am|pm)$/.test(text) ? `today at ${text}` : `on ${text}`;
}

/** A YYYY-MM-DD as "Wed, May 20" (built from parts: no time zone shift). */
export function day(ymd: string): string {
  return parseYmd(ymd).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

/** Trello's due chip: grey later, yellow due today or tomorrow, red a day late,
 *  pink later than that, green once done. */
export function dueTone(due: string, completed: boolean, today: string): string {
  if (completed) return 'bg-[#e3fcef] text-[#1f845a]';
  const [y, m, d] = today.split('-').map(Number);
  const shift = (n: number) => {
    const t = new Date(y, m - 1, d + n);
    return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
  };
  if (due < shift(-1)) return 'bg-[#ffedeb] text-[#ae2e24]';
  if (due < today) return 'bg-[#c9372c] text-white';
  if (due <= shift(1)) return 'bg-[#f5cd47] text-[#172b4d]';
  return 'bg-bc-wash text-bc-subtle';
}

/** A local date as YYYY-MM-DD, and back. */
export const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export function parseYmd(s: string): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/** Markdown as one plain line, for previews and excerpts. */
export function plain(md: string): string {
  return md
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#*_`>~]|^\s*[-+] (\[[ x]\] )?/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// ── People ────────────────────────────────────────────────────────────────────

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '?') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

/** A round avatar: the person's initials on their colour. An AI tool's has a small spark. */
export function Avatar({ person, size = 32 }: { person: Person | null | undefined; size?: number }) {
  const name = person?.name ?? 'Someone';
  return (
    <span
      title={person?.kind === 'ai' ? `${name} (AI tool)` : name}
      className="relative inline-flex shrink-0 select-none items-center justify-center rounded-full font-bold text-white"
      style={{ width: size, height: size, fontSize: Math.max(9, size * 0.38), background: person?.color || '#9a9fa2' }}
    >
      {initials(name)}
      {person?.kind === 'ai' && (
        <span
          aria-hidden
          className="absolute -bottom-0.5 -right-0.5 rounded-full bg-bc-canvas leading-none"
          style={{ fontSize: Math.max(8, size * 0.32) }}
        >
          ✦
        </span>
      )}
    </span>
  );
}

export function AvatarStack({ people, size = 28, max = 8 }: { people: Person[]; size?: number; max?: number }) {
  const shown = people.slice(0, max);
  return (
    <span className="inline-flex items-center">
      {shown.map((p, i) => (
        <span key={p.id} className="rounded-full ring-2 ring-bc-canvas" style={{ marginLeft: i ? -size * 0.25 : 0 }}>
          <Avatar person={p} size={size} />
        </span>
      ))}
      {people.length > max && (
        <span className="ml-1 rounded-full bg-bc-wash px-2 text-xs font-semibold text-bc-subtle">
          +{people.length - max}
        </span>
      )}
    </span>
  );
}

/** "Me", "Ana", "Claude" — first names, as Basecamp's chips show them. */
export function names(people: Person[]): string {
  return people.map((p) => p.name).join(', ');
}

// ── The panel and its breadcrumb row ──────────────────────────────────────────

export function Perma({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return <div className={wide ? 'bc-perma bc-perma-wide' : 'bc-perma'}>{children}</div>;
}

export interface Crumb {
  label: string;
  to?: string;
}

/** Where each tool lives under /p/:id. */
export const TOOL_PATH: Record<Tool, string> = {
  message_board: 'messages',
  todoset: 'todos',
  vault: 'docs',
  chat: 'chat',
  schedule: 'calendar',
  questionnaire: 'checkins',
  kanban_board: 'cards',
  doors: 'doors',
};

const tabCls = (active: boolean) =>
  `-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-[15px] ${active ? 'border-bc-blue font-bold text-bc-ink' : 'border-transparent text-bc-subtle hover:text-bc-ink'}`;

/** A project's header, with suite navigation: back to every project, the name, and a
 * tab for each place in it — the Board first (where a project opens, unless its board
 * is switched off), the Overview, then each tool that is on. The shell draws it, so it
 * sits still from tab to tab. */
export function ProjectHeader({ project }: { project: Project }) {
  const { pathname } = useLocation();
  const base = `/p/${project.id}`;
  const onBoard = pathname === base || pathname === `${base}/cards`;
  const board = project.dock.find((t) => t.tool === 'kanban_board' && t.enabled);
  const tools = project.dock.filter((t) => t.enabled && t.tool !== 'kanban_board');
  return (
    <div className="mb-4">
      <Link to="/" className="text-sm text-bc-blue hover:underline">
        ← All projects
      </Link>
      <div className="mt-1 flex items-center gap-2">
        <h1 className="min-w-0 truncate text-2xl font-bold">{project.name}</h1>
        {project.sample && (
          <span className="shrink-0 rounded bg-amber-300 px-2 py-0.5 text-sm font-extrabold text-amber-950">
            Sample project
          </span>
        )}
      </div>
      <nav aria-label="Project" className="mt-2 flex overflow-x-auto border-b border-bc-line">
        {board && (
          <Link to={base} aria-current={onBoard ? 'page' : undefined} className={tabCls(onBoard)}>
            {board.title}
          </Link>
        )}
        <NavLink to={`${base}/overview`} className={({ isActive }) => tabCls(isActive)}>
          Overview
        </NavLink>
        {tools.map((t) => (
          <NavLink key={t.tool} to={`${base}/${TOOL_PATH[t.tool]}`} className={({ isActive }) => tabCls(isActive)}>
            {t.title}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

/** The row at the top of a page: "Project ‹ Tool ‹ …" on the left, actions on the
 * right. A page the header's tabs reach ("Home ‹ My Tasks"), or a project's page under
 * its tabs (`project`), needs no trail: just the actions. */
export function Crumbs({ crumbs, right, project }: { crumbs: Crumb[]; right?: ReactNode; project?: Project | null }) {
  if (project || (crumbs.length <= 2 && crumbs[0]?.to === '/')) {
    return right ? <div className="float-right -mt-1 mb-2 ml-3 flex items-center gap-2">{right}</div> : null;
  }
  return (
    <div className="-mx-1 mb-4 flex min-h-10 flex-wrap items-center gap-x-2 gap-y-1 border-b border-bc-line px-1 pb-3">
      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-wrap items-center gap-1.5 text-[15px]">
        {crumbs.map((c, i) => (
          <span key={i} className="flex min-w-0 items-center gap-1.5">
            {i > 0 && (
              <span aria-hidden className="text-bc-faint">
                ‹
              </span>
            )}
            {c.to ? (
              <Link to={c.to} className={`truncate hover:underline ${i === 0 ? 'font-bold' : ''}`}>
                {c.label}
              </Link>
            ) : (
              <span className={`truncate ${i === 0 ? 'font-bold' : 'text-bc-subtle'}`}>{c.label}</span>
            )}
          </span>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2">{right}</div>
    </div>
  );
}

export function ToolHeading({ children }: { children: ReactNode }) {
  return <h2 className="text-[17px] font-bold text-bc-heading">{children}</h2>;
}

// ── The ••• menu ──────────────────────────────────────────────────────────────

export interface MenuItem {
  label: string;
  onClick: () => void;
  danger?: boolean;
  hidden?: boolean;
}

/** `up` opens it above the button (on the bottom bar), from its left edge. */
export function Menu({
  items,
  label = 'More options',
  up = false,
}: {
  items: (MenuItem | 'sep')[];
  label?: string;
  up?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  const shown = items.filter((i) => i === 'sep' || !i.hidden);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 w-9 items-center justify-center rounded-lg text-lg leading-none text-bc-subtle hover:bg-bc-line/60 hover:text-bc-ink"
      >
        •••
      </button>
      {open && (
        <div
          role="menu"
          className={`absolute z-40 min-w-52 rounded-lg border border-bc-line bg-bc-canvas py-1 shadow-xl ${up ? 'bottom-full left-0 mb-1' : 'right-0 mt-1'}`}
        >
          {shown.map((item, i) =>
            item === 'sep' ? (
              <div key={i} className="my-1 border-t border-bc-line" />
            ) : (
              <button
                key={i}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  item.onClick();
                }}
                className={`block w-full px-4 py-2 text-left text-[15px] hover:bg-bc-wash ${item.danger ? 'text-bc-unread' : ''}`}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

// ── Boosts ────────────────────────────────────────────────────────────────────

const QUICK = ['👍', '👏', '👋', '❤️', '😂', '😊', '🎉'];

/** A row of boost pills and the 🚀 button that adds one (an emoji or up to 16 characters). */
export function Boosts({
  boosts,
  onBoost,
  onRemove,
}: {
  boosts: Boost[];
  onBoost: (content: string) => Promise<unknown>;
  onRemove: (id: number) => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const send = async (content: string) => {
    if (!content.trim()) return;
    setOpen(false);
    setText('');
    await onBoost(content.trim());
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {boosts.map((b) => (
        <button
          key={b.id}
          type="button"
          className="bc-boost"
          title={`${b.booster?.name ?? ''} — click to take it back`}
          onClick={() => {
            if (b.booster?.kind === 'me' && confirm('Remove this reaction?')) void onRemove(b.id);
          }}
        >
          <Avatar person={b.booster} size={26} />
          <span className="text-[15px]">{b.content}</span>
        </button>
      ))}
      <div className="relative">
        <button
          type="button"
          aria-label="React"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="flex h-8 w-8 items-center justify-center rounded-full border border-bc-line bg-bc-canvas text-sm hover:bg-bc-wash"
        >
          🚀
        </button>
        {open && (
          <div className="absolute left-0 z-30 mt-1 flex items-center gap-1 rounded-full border border-bc-line bg-bc-canvas p-1 shadow-lg">
            {QUICK.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => void send(e)}
                className="rounded-full px-1.5 text-lg hover:bg-bc-wash"
              >
                {e}
              </button>
            ))}
            <form
              onSubmit={(ev) => {
                ev.preventDefault();
                void send(text);
              }}
            >
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={16}
                placeholder="Type…"
                aria-label="Reaction"
                className="w-20 rounded-full border border-bc-line bg-bc-canvas px-2 py-0.5 text-sm"
              />
            </form>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Text ──────────────────────────────────────────────────────────────────────

// The account's people, by name, for @mentions: set by PeopleProvider (ProjectsShell).
let mentionNames: string[] = [];
export function setMentionNames(names: string[]) {
  mentionNames = [...names].sort((a, b) => b.length - a.length);
}
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** @Name for someone on the account, in bold, as Basecamp marks a mention: after a
 * space or an opening bracket or quote only, so an address (x@Ann, …/@Ann) is left alone.
 * simplification: the Markdown source is rewritten, so "`code @Ann`" shows the stars; a
 * remark plugin on text nodes is the way up. */
export function markMentions(text: string): string {
  let out = text;
  for (const name of mentionNames) {
    out = out.replace(new RegExp(`(^|[\\s([{"'])@(${escapeRe(name)})(?![\\w])`, 'gi'), '$1**@$2**');
  }
  return out;
}

export function Body({ text }: { text: string }) {
  return <Markdown body={markMentions(text)} className="bc-body text-bc-ink" />;
}

/** While an @name is being typed at the end of `text`: the people it could be, to pick. */
export function MentionPicker({ text, onPick }: { text: string; onPick: (next: string) => void }) {
  const typed = /(^|\s)@([^@\n]{0,24})$/.exec(text);
  if (!typed) return null;
  const start = typed[2].toLowerCase();
  const matches = mentionNames
    .filter((n) => n.toLowerCase().startsWith(start) && n.toLowerCase() !== start)
    .slice(0, 5);
  if (!matches.length) return null;
  return (
    <div role="listbox" aria-label="Mention someone" className="mt-1 flex flex-wrap gap-1">
      {matches.map((n) => (
        <button
          key={n}
          type="button"
          role="option"
          aria-selected={false}
          className="rounded-full border border-bc-line bg-bc-canvas px-2 py-0.5 text-[13px] hover:bg-bc-wash"
          onClick={() => onPick(`${text.slice(0, text.length - typed[2].length)}${n} `)}
        >
          @{n}
        </button>
      ))}
    </div>
  );
}

/** A textarea that grows with its text; ⌘/Ctrl+Enter submits. Markdown. */
export function Composer({
  placeholder,
  initial = '',
  submitLabel = 'Add this comment',
  onSubmit,
  onCancel,
  autoFocus,
}: {
  placeholder: string;
  initial?: string;
  submitLabel?: string;
  onSubmit: (text: string) => Promise<unknown>;
  onCancel?: () => void;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      await onSubmit(text);
      setText('');
    } catch (e) {
      setError(apiErrorMessage(e, 'That did not save. Try again.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <textarea
        value={text}
        placeholder={placeholder}
        autoFocus={autoFocus}
        maxLength={20000}
        onChange={(e) => {
          setText(e.target.value);
          e.target.style.height = 'auto';
          e.target.style.height = `${e.target.scrollHeight}px`;
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit();
          }
        }}
        rows={3}
        className="bc-input min-h-24 resize-none text-[17px]"
      />
      <MentionPicker text={text} onPick={setText} />
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          className="bc-btn bc-btn-primary"
          disabled={!text.trim() || busy}
          onClick={() => void submit()}
        >
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="bc-btn" onClick={onCancel}>
            Cancel
          </button>
        )}
        <span className="text-xs text-bc-subtle">
          Markdown works: **bold**, - lists, [links](https://…); @Name mentions someone
        </span>
      </div>
      {error && (
        <p role="alert" className="mt-1 text-sm text-bc-unread">
          {error}
        </p>
      )}
    </div>
  );
}

// ── Comments ──────────────────────────────────────────────────────────────────

export function Comments({
  comments,
  me,
  onAdd,
  onBoost,
  onRemoveBoost,
}: {
  comments: Item[];
  me: Person | null;
  onAdd: (text: string) => Promise<unknown>;
  onBoost: (commentId: number, content: string) => Promise<unknown>;
  onRemoveBoost: (boostId: number) => Promise<unknown>;
}) {
  const [writing, setWriting] = useState(false);
  return (
    <section aria-label="Comments" className="mt-8">
      <div className="flex items-end gap-3 border-b border-bc-line">
        <span className="-mb-px rounded-t-md border border-b-bc-canvas border-bc-line bg-bc-canvas px-3 py-1.5 text-[15px] font-semibold">
          Comments{comments.length ? ` (${comments.length})` : ''}
        </span>
      </div>
      <ul>
        {comments.map((c) => (
          <li key={c.id} id={`comment-${c.id}`} className="flex gap-3 border-b border-bc-line py-4">
            <Avatar person={c.creator} size={40} />
            <div className="min-w-0 flex-1">
              <p className="text-[15px]">
                <span className="font-bold">{c.creator?.name ?? 'Someone'}</span>
                {c.creator?.kind === 'ai' && <span className="text-bc-subtle">, AI tool</span>}
                <span className="text-bc-subtle"> • {when(c.created_at)}</span>
              </p>
              <div className="mt-1">
                <Body text={c.body} />
              </div>
              <div className="mt-2">
                <Boosts
                  boosts={c.boosts ?? []}
                  onBoost={(content) => onBoost(c.id, content)}
                  onRemove={onRemoveBoost}
                />
              </div>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex gap-3">
        <Avatar person={me} size={40} />
        <div className="min-w-0 flex-1">
          {writing ? (
            <Composer
              placeholder="Add your comment…"
              autoFocus
              onSubmit={async (t) => {
                await onAdd(t);
                setWriting(false);
              }}
              onCancel={() => setWriting(false)}
            />
          ) : (
            <button
              type="button"
              onClick={() => setWriting(true)}
              className="w-full rounded-lg border border-bc-line px-4 py-3 text-left text-[17px] text-bc-faint hover:border-bc-faint"
            >
              Add your comment…
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

// ── Small things ──────────────────────────────────────────────────────────────

/** Basecamp's progress pie: the done share of a circle, in the list's colour. */
export function ProgressPie({
  done,
  total,
  size = 22,
  color = 'var(--color-bc-green)',
}: {
  done: number;
  total: number;
  size?: number;
  color?: string;
}) {
  const share = total ? done / total : 0;
  const r = size / 2;
  const angle = share * 2 * Math.PI;
  const x = r + r * Math.sin(angle);
  const y = r - r * Math.cos(angle);
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-label={`${done} of ${total} done`}
      role="img"
      className="shrink-0"
    >
      <circle cx={r} cy={r} r={r} fill="var(--color-bc-line)" />
      {share >= 1 ? (
        <circle cx={r} cy={r} r={r} fill={color} />
      ) : (
        share > 0 && <path d={`M${r},${r} L${r},0 A${r},${r} 0 ${share > 0.5 ? 1 : 0},1 ${x},${y} Z`} fill={color} />
      )}
    </svg>
  );
}

/** The chip after a to-do's title: who, when, subtasks. */
export function Chip({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full bg-bc-wash px-2 py-0.5 text-[13px] text-bc-subtle ${tone}`}
    >
      {children}
    </span>
  );
}

export const COLORS = [
  '',
  'red',
  'orange',
  'yellow',
  'green',
  'blue',
  'aqua',
  'purple',
  'gray',
  'pink',
  'brown',
] as const;

export function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Colour">
      {COLORS.map((c) => (
        <button
          key={c || 'none'}
          type="button"
          role="radio"
          aria-checked={value === c}
          aria-label={c || 'No colour'}
          onClick={() => onChange(c)}
          className={`bc-c-${c} h-7 w-7 rounded-full border-2 ${value === c ? 'border-bc-ink' : 'border-transparent'}`}
          style={{ background: c ? 'var(--c)' : 'var(--color-bc-wash)' }}
        />
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-bc-line px-6 py-10 text-center">
      <p className="text-lg font-bold">{title}</p>
      {children && <div className="mt-2 text-bc-subtle">{children}</div>}
    </div>
  );
}

/** Where an activity row or a bookmark leads. */
export function itemPath(
  projectId: number,
  item: { recording_id?: number | null; card_id?: number | null; action?: string },
): string {
  if (item.recording_id) return `/i/${item.recording_id}`;
  if (item.card_id) return `/p/${projectId}/cards?card=${item.card_id}`;
  if (item.action === 'chatted') return `/p/${projectId}/chat`;
  return `/p/${projectId}`;
}
