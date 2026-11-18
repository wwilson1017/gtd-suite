// Projects GTD — New for you, Basecamp 5's sidebar (Shift+S): what everyone else
// did lately (here mostly your AI tools), one entry per item with how much
// happened since you looked; what you bubbled up to come back to; and what is
// due. Hover an entry to mark it read (✕), bubble it up (🫧), stop hearing about it
// (🔕) or, once read, mark it unread again. "Shhh until tomorrow" quiets the count.
// A filter at the bottom, as Basecamp's has.
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { todayStr } from '../todo-gtd/util';
import {
  BUBBLE_TIMES,
  bubbleUp,
  getInbox,
  inboxTarget,
  markAllRead,
  markRead,
  setMuted,
  type Inbox,
  type InboxItem,
} from './api';
import { Avatar, day, itemPath, when } from './ui';

// Basecamp's "Shhh until tomorrow": the unread count keeps quiet in this browser
// until the next day. Remembered per browser; nothing changes on the server.
const SHHH_KEY = 'bc-shhh-until';

/** The day after `today` (YYYY-MM-DD), by the calendar. */
export function nextDay(today: string): string {
  const d = new Date(`${today}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** Whether the count keeps quiet today, and the switch. Read again every minute, so a
 * page left open overnight speaks up when the next day comes. */
export function useShhh(): [boolean, (on: boolean) => void] {
  const read = () => {
    try {
      return (localStorage.getItem(SHHH_KEY) ?? '') > todayStr();
    } catch {
      return false;
    }
  };
  const [quiet, setQuiet] = useState(read);
  useEffect(() => {
    const timer = window.setInterval(() => setQuiet(read()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const set = (on: boolean) => {
    try {
      if (on) localStorage.setItem(SHHH_KEY, nextDay(todayStr()));
      else localStorage.removeItem(SHHH_KEY);
    } catch {
      /* a private window: this page only */
    }
    setQuiet(on);
  };
  return [quiet, set];
}

function link(i: {
  recording_id: number | null;
  card_id: number | null;
  board_id: number;
  last?: InboxItem['last'];
}): string {
  return itemPath(i.board_id, { ...i, action: i.last?.action });
}

function Entry({ item, onChange, onGo }: { item: InboxItem; onChange: () => void; onGo: () => void }) {
  const [bubbling, setBubbling] = useState(false);
  const target = inboxTarget(item);
  return (
    <li className="group relative rounded-lg px-2 py-2 hover:bg-bc-wash">
      <Link
        to={link(item)}
        onClick={() => {
          void markRead(target).then(onChange);
          onGo();
        }}
        className="flex gap-2.5"
      >
        <Avatar person={item.last?.creator} size={32} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-bold">{item.title}</span>
          {item.last && (
            <span className="line-clamp-2 block text-[14px] text-bc-subtle">
              {item.last.creator?.name} {item.last.verb}
              {item.last.detail ? `: ${item.last.detail}` : ''}
            </span>
          )}
          <span className="block text-[12px] text-bc-faint">
            {item.muted ? '🔕 ' : ''}
            {item.last ? when(item.last.created_at) : item.bubble_up_at ? 'Reminder' : 'Marked unread'} ·{' '}
            {item.board_name}
            {item.people.length > 1 ? ` · ${item.people.join(', ')}` : ''}
          </span>
        </span>
        {item.unread_count > 0 && (
          <span className="mt-1 h-5 min-w-5 shrink-0 rounded-full bg-bc-unread px-1.5 text-center text-[12px] font-bold leading-5 text-white">
            {item.unread_count}
          </span>
        )}
      </Link>
      <span className="absolute right-1 top-1 hidden gap-1 group-hover:flex group-focus-within:flex">
        {item.unread_count > 0 ? (
          <button
            type="button"
            title="Mark read"
            aria-label={`Mark ${item.title} read`}
            onClick={() => void markRead(target).then(onChange)}
            className="rounded-full bg-bc-canvas px-1.5 text-[13px] shadow"
          >
            ✕
          </button>
        ) : (
          <button
            type="button"
            title="Mark unread"
            aria-label={`Mark ${item.title} unread`}
            onClick={() => void markRead(target, false).then(onChange)}
            className="rounded-full bg-bc-canvas px-1.5 text-[13px] shadow"
          >
            ●
          </button>
        )}
        {/* Quiet because its whole project is: the bell turns the project back on. */}
        <button
          type="button"
          title={item.muted ? 'Notify me again' : "Don't notify me"}
          aria-label={
            item.project_muted
              ? `Notify me about ${item.board_name} again`
              : item.muted
                ? `Notify me about ${item.title} again`
                : `Don't notify me about ${item.title}`
          }
          onClick={() =>
            void (
              item.project_muted ? setMuted({ project_id: item.board_id }, false) : setMuted(target, !item.muted)
            ).then(onChange)
          }
          className="rounded-full bg-bc-canvas px-1.5 text-[13px] shadow"
        >
          {item.muted ? '🔔' : '🔕'}
        </button>
        <button
          type="button"
          title="Remind me later"
          aria-label={`Remind me later about ${item.title}`}
          aria-expanded={bubbling}
          onClick={() => setBubbling((b) => !b)}
          className="rounded-full bg-bc-canvas px-1.5 text-[13px] shadow"
        >
          🫧
        </button>
      </span>
      {bubbling && (
        <div className="mt-1 flex flex-wrap gap-1 pl-10">
          {BUBBLE_TIMES.filter(([w]) => w !== 'now').map(([w, label]) => (
            <button
              key={w}
              type="button"
              className="rounded-full border border-bc-line bg-bc-canvas px-2 text-[13px] hover:bg-bc-wash"
              onClick={() => {
                setBubbling(false);
                void bubbleUp(target, w).then(onChange);
              }}
            >
              {label}
            </button>
          ))}
          {item.bubble_up_at && (
            <button
              type="button"
              className="rounded-full border border-bc-line px-2 text-[13px]"
              onClick={() => {
                setBubbling(false);
                void bubbleUp(target, null).then(onChange);
              }}
            >
              Take it off
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export function NewForYou({
  onClose,
  onCount,
  quiet,
  setQuiet,
}: {
  onClose: () => void;
  onCount: (n: number) => void;
  quiet: boolean;
  setQuiet: (on: boolean) => void;
}) {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(() => {
    getInbox().then(
      (i) => {
        setInbox(i);
        onCount(i.unread_count);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load your notifications.')),
    );
  }, [onCount]);
  useEffect(load, [load]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [onClose]);
  const f = filter.trim().toLowerCase();
  const keep = (i: InboxItem) => !f || `${i.title} ${i.board_name} ${i.people.join(' ')}`.toLowerCase().includes(f);
  const section = (title: string, tone: string, items: InboxItem[], extra?: React.ReactNode) =>
    items.length > 0 && (
      <section className="mt-4">
        <h3 className={`flex items-center px-2 text-[13px] font-bold uppercase tracking-wider ${tone}`}>
          {title}
          {extra}
        </h3>
        <ul className="mt-1">
          {items.filter(keep).map((i) => (
            <Entry key={i.key} item={i} onChange={load} onGo={onClose} />
          ))}
        </ul>
      </section>
    );
  return (
    <aside
      role="dialog"
      aria-label="Notifications"
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-bc-line bg-bc-canvas shadow-2xl sm:w-[clamp(400px,25vw,560px)]"
    >
      <header className="flex items-center gap-2 border-b border-bc-line px-4 py-3">
        <h2 className="text-lg font-extrabold">Notifications</h2>
        <button
          type="button"
          onClick={() => setQuiet(!quiet)}
          aria-pressed={quiet}
          className="rounded-full border border-bc-line px-2.5 py-0.5 text-[13px] hover:bg-bc-wash"
        >
          {quiet ? '🤫 Quiet is on: turn it off' : '🤫 Quiet until tomorrow'}
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="ml-auto text-2xl leading-none text-bc-subtle hover:text-bc-ink"
        >
          &times;
        </button>
      </header>
      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {error && (
          <p role="alert" className="mt-3 px-2 text-bc-unread">
            {error}
          </p>
        )}
        {inbox && inbox.due.length > 0 && (
          <section className="mt-3">
            <h3 className="px-2 text-[13px] font-bold uppercase tracking-wider text-[#a54800]">Due soon</h3>
            <ul className="mt-1">
              {inbox.due.map((d) => (
                <li key={`${d.recording_id}-${d.card_id}`}>
                  <Link
                    to={link(d)}
                    onClick={onClose}
                    className="flex items-baseline gap-2 rounded-lg px-2 py-1.5 hover:bg-bc-wash"
                  >
                    <span className="truncate text-[15px]">{d.title}</span>
                    <span className="ml-auto shrink-0 text-[13px] text-bc-subtle">{day(d.due)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
        {inbox && section('Reminders', 'text-bc-blue', inbox.bubbled)}
        {inbox &&
          section(
            'New',
            'text-[#d9531e]',
            inbox.unread,
            <button
              type="button"
              className="ml-auto text-[12px] font-normal normal-case tracking-normal text-bc-blue underline"
              onClick={() => void markAllRead().then(load)}
            >
              Mark all read
            </button>,
          )}
        {inbox && inbox.unread.length === 0 && inbox.bubbled.length === 0 && (
          <p className="mt-6 text-center text-bc-subtle">You're all caught up. 🎉</p>
        )}
        {inbox && section('Previous notifications', 'text-bc-subtle', inbox.previous)}
        {inbox && inbox.scheduled_bubble_ups > 0 && (
          <p className="mt-3 px-2 text-[13px] text-bc-subtle">
            {inbox.scheduled_bubble_ups} more will bubble up later.
          </p>
        )}
      </div>
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter…"
        aria-label="Filter notifications"
        className="m-3 rounded-lg border border-bc-line bg-bc-canvas px-3 py-2"
      />
    </aside>
  );
}
