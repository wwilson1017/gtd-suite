// Projects GTD — the Calendar, as Basecamp 5's: a month grid (today on a pale
// yellow, a circled event stands out) or an agenda list, events and, unless
// switched off, the to-dos, subtasks and cards due. One project's, or every
// project's (key 2). "+ New event": a title, a day or days, all day or a time,
// a repeat, a join link, notes. As in Trello's calendar, drag an event or a due
// to-do or card onto another day to move it there.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { todayStr } from '../todo-gtd/util';
import { createItem, getCalendar, getProject, listBoards, updateCard, updateItem } from './api';
import { ProjectsShell } from './ProjectsShell';
import type { BoardSummary, CalendarRange, DueOnCalendar, Occurrence, Project } from './types';
import { Crumbs, Perma, day, parseYmd as parse, ymd } from './ui';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
export const REPEATS: [string, string][] = [
  ['', 'Does not repeat'],
  ['every_day', 'Every day'],
  ['every_weekday', 'Every weekday'],
  ['every_week', 'Every week'],
  ['every_other_week', 'Every other week'],
  ['every_month', 'Every month'],
  ['every_year', 'Every year'],
];

/** The 6 weeks shown for a month, Sunday first. */
function grid(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay());
  return Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
}

/** "8:30am–8:45am", or the start alone for a month cell. */
function timeLabel(e: Occurrence, startOnly = false): string {
  if (e.all_day || !e.starts_at) return '';
  const fmt = (t: string) => {
    const [h, m] = t.split(':').map(Number);
    return `${h % 12 || 12}${m ? `:${String(m).padStart(2, '0')}` : ''}${h < 12 ? 'am' : 'pm'}`;
  };
  return e.ends_at && !startOnly ? `${fmt(e.starts_at)}–${fmt(e.ends_at)}` : fmt(e.starts_at);
}

const shiftDay = (ymdStr: string, days: number) => {
  const d = parse(ymdStr);
  return ymd(new Date(d.getFullYear(), d.getMonth(), d.getDate() + days));
};
const daysBetween = (a: string, b: string) => Math.round((parse(b).getTime() - parse(a).getTime()) / 86_400_000);

/** Move what was dropped on a day: an event's whole span (a repeating one from its first day), or a due date. */
async function moveTo(drag: string, target: string): Promise<void> {
  const what = JSON.parse(drag) as {
    kind: string;
    id: number;
    on: string;
    starts_on?: string;
    ends_on?: string | null;
  };
  if (what.kind === 'event') {
    const by = daysBetween(what.on, target);
    if (!by || !what.starts_on) return;
    await updateItem(what.id, {
      starts_on: shiftDay(what.starts_on, by),
      ends_on: what.ends_on ? shiftDay(what.ends_on, by) : null,
    });
  } else if (what.kind === 'card') {
    await updateCard(what.id, { due_date: target });
  } else {
    await updateItem(what.id, { due_on: target });
  }
}

export function dueLink(d: { kind: string; id: number; board_id: number; parent_id: number | null }): string {
  if (d.kind === 'card') return `/p/${d.board_id}/cards?card=${d.id}`;
  return `/i/${d.kind === 'step' && d.parent_id ? d.parent_id : d.id}`;
}

function NewEvent({
  projects,
  fixedProject,
  onDone,
  initialDay,
}: {
  projects: BoardSummary[];
  fixedProject?: number;
  onDone: (made: boolean) => void;
  initialDay: string;
}) {
  const [project, setProject] = useState<number>(fixedProject ?? projects[0]?.id ?? 0);
  const [title, setTitle] = useState('');
  const [starts, setStarts] = useState(initialDay);
  const [ends, setEnds] = useState(initialDay);
  const [allDay, setAllDay] = useState(true);
  const [at, setAt] = useState('09:00');
  const [until, setUntil] = useState('10:00');
  const [repeat, setRepeat] = useState('');
  const [url, setUrl] = useState('');
  const [notes, setNotes] = useState('');
  const [circle, setCircle] = useState(false);
  const [error, setError] = useState('');
  const save = async () => {
    try {
      await createItem(project, 'schedule_entry', {
        title: title.trim(),
        starts_on: starts,
        ends_on: ends < starts ? starts : ends,
        all_day: allDay,
        ...(allDay ? {} : { starts_at: at, ends_at: until }),
        ...(repeat ? { repeat } : {}),
        ...(url.trim() ? { url: url.trim() } : {}),
        ...(notes ? { body: notes } : {}),
        highlighted: circle,
      });
      onDone(true);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save the event.'));
    }
  };
  return (
    <form
      className="mt-4 rounded-lg border border-bc-line p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <p className="font-bold">New event</p>
      {!fixedProject && (
        <select
          value={project}
          onChange={(e) => setProject(Number(e.target.value))}
          aria-label="Project"
          className="bc-input mt-2"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        placeholder="Name the event…"
        aria-label="Event"
        maxLength={500}
        className="bc-input mt-2 text-[18px] font-bold"
      />
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[15px]">
        <input
          type="date"
          value={starts}
          onChange={(e) => {
            setStarts(e.target.value);
            if (ends < e.target.value) setEnds(e.target.value);
          }}
          aria-label="Starts"
          className="bc-input w-auto py-1"
        />
        <span>to</span>
        <input
          type="date"
          value={ends}
          min={starts}
          onChange={(e) => setEnds(e.target.value)}
          aria-label="Ends"
          className="bc-input w-auto py-1"
        />
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            className="bc-checkbox"
            checked={allDay}
            onChange={(e) => setAllDay(e.target.checked)}
          />{' '}
          All day
        </label>
        {!allDay && (
          <>
            <input
              type="time"
              value={at}
              onChange={(e) => setAt(e.target.value)}
              aria-label="From"
              className="bc-input w-auto py-1"
            />
            <span>–</span>
            <input
              type="time"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              aria-label="Until"
              className="bc-input w-auto py-1"
            />
          </>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[15px]">
        <select
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          aria-label="Repeat"
          className="bc-input w-auto py-1"
        >
          {REPEATS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            className="bc-checkbox"
            checked={circle}
            onChange={(e) => setCircle(e.target.checked)}
          />{' '}
          Circle it
        </label>
      </div>
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Join link (Zoom, Meet…), optional"
        aria-label="Join link"
        maxLength={500}
        className="bc-input mt-2"
      />
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        rows={2}
        placeholder="Notes (optional)"
        aria-label="Notes"
        maxLength={20000}
        className="bc-input mt-2"
      />
      {error && (
        <p role="alert" className="mt-1 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button type="submit" className="bc-btn bc-btn-primary" disabled={!title.trim() || !project}>
          Post this event
        </button>
        <button type="button" className="bc-btn" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function CalendarPage() {
  const params = useParams();
  const projectId = params.id ? Number(params.id) : undefined;
  const today = todayStr();
  const [month, setMonth] = useState(() => {
    const t = parse(today);
    return new Date(t.getFullYear(), t.getMonth(), 1);
  });
  const [mode, setMode] = useState<'month' | 'agenda'>('month');
  const [withDue, setWithDue] = useState(true);
  const [range, setRange] = useState<CalendarRange | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<BoardSummary[]>([]);
  const [making, setMaking] = useState<string | null>(null);
  const [error, setError] = useState('');
  const days = useMemo(() => grid(month), [month]);
  const load = useCallback(() => {
    const first = mode === 'month' ? ymd(days[0]) : ymd(month);
    const last = mode === 'month' ? ymd(days[41]) : ymd(new Date(month.getFullYear(), month.getMonth() + 3, 0));
    getCalendar(first, last, projectId, withDue).then(setRange, (e) =>
      setError(apiErrorMessage(e, 'Could not load the calendar.')),
    );
  }, [days, month, mode, projectId, withDue]);
  useEffect(load, [load]);
  useEffect(() => {
    if (projectId) getProject(projectId).then(setProject, () => {});
    else listBoards().then(setProjects, () => {});
  }, [projectId]);

  const byDay = useMemo(() => {
    const map = new Map<string, { events: Occurrence[]; due: DueOnCalendar[] }>();
    const slot = (d: string) => map.get(d) ?? map.set(d, { events: [], due: [] }).get(d)!;
    for (const e of range?.events ?? []) {
      for (let d = parse(e.on); ymd(d) <= e.until; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1))
        slot(ymd(d)).events.push(e);
    }
    for (const d of range?.due ?? []) slot(d.on).due.push(d);
    return map;
  }, [range]);
  const title = projectId ? (project?.dock.find((t) => t.tool === 'schedule')?.title ?? 'Calendar') : 'Calendar';
  const shift = (n: number) => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + n, 1));
  const monthName = month.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

  // `cell` is the day the chip is drawn on: a drag moves the event by the days from there.
  const eventChip = (e: Occurrence, cell: string) => (
    <Link
      key={`${e.id}-${e.on}`}
      to={`/i/${e.id}`}
      title={`${e.title}${e.board_name && !projectId ? ` — ${e.board_name}` : ''}`}
      draggable
      onDragStart={(ev) =>
        ev.dataTransfer.setData(
          'application/x-bc-day',
          JSON.stringify({ kind: 'event', id: e.id, on: cell, starts_on: e.starts_on, ends_on: e.due_on }),
        )
      }
      className={`block truncate rounded px-1 text-[12px] leading-5 ${e.highlighted ? 'border border-bc-ink font-bold' : ''} bg-bc-highlight text-bc-ink hover:underline`}
    >
      {e.repeat ? '🔁 ' : ''}
      {timeLabel(e, true) && <span className="text-bc-subtle">{timeLabel(e, true)} </span>}
      {e.title}
    </Link>
  );
  const dueChip = (d: DueOnCalendar) => (
    <Link
      key={`${d.kind}-${d.id}`}
      to={dueLink(d)}
      draggable
      onDragStart={(ev) =>
        ev.dataTransfer.setData('application/x-bc-day', JSON.stringify({ kind: d.kind, id: d.id, on: d.on }))
      }
      className="block truncate px-1 text-[12px] leading-5 text-bc-subtle hover:underline"
    >
      {d.kind === 'card' ? '▤' : '☐'} {d.title}
    </Link>
  );

  return (
    <ProjectsShell
      project={projectId ? project : null}
      title={projectId ? `${title} · ${project?.name ?? ''}` : 'Calendar'}
    >
      <Perma wide={mode === 'month'}>
        <Crumbs
          project={projectId ? project : null}
          crumbs={
            projectId
              ? [{ label: project?.name ?? '…', to: `/p/${projectId}` }, { label: title }]
              : [{ label: 'Home', to: '/' }, { label: 'Calendar' }]
          }
        />
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="bc-title mr-auto text-2xl">{title}</h1>
          <button type="button" className="bc-btn bc-btn-sm" onClick={() => shift(-1)} aria-label="Previous month">
            ←
          </button>
          <button
            type="button"
            className="bc-btn bc-btn-sm"
            onClick={() => {
              const t = parse(today);
              setMonth(new Date(t.getFullYear(), t.getMonth(), 1));
            }}
          >
            Today
          </button>
          <button type="button" className="bc-btn bc-btn-sm" onClick={() => shift(1)} aria-label="Next month">
            →
          </button>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as typeof mode)}
            aria-label="View"
            className="bc-input w-auto py-1 text-[14px]"
          >
            <option value="month">Calendar</option>
            <option value="agenda">Agenda</option>
          </select>
          <label className="flex items-center gap-1.5 text-[14px]">
            <input
              type="checkbox"
              className="bc-checkbox"
              checked={withDue}
              onChange={(e) => setWithDue(e.target.checked)}
            />{' '}
            Show what's due
          </label>
          <button type="button" className="bc-btn bc-btn-primary bc-btn-sm" onClick={() => setMaking(today)}>
            ＋ New event
          </button>
        </div>
        {making && (
          <NewEvent
            projects={projects}
            fixedProject={projectId}
            initialDay={making}
            onDone={(made) => {
              setMaking(null);
              if (made) load();
            }}
          />
        )}
        {error && (
          <p role="alert" className="mt-3 text-bc-unread">
            {error}
          </p>
        )}
        <h2 className="mt-4 text-[20px] font-bold">{monthName}</h2>
        {mode === 'month' ? (
          <div className="mt-2 overflow-x-auto">
            <div className="grid min-w-[700px] grid-cols-7 border-l border-t border-bc-line">
              {WEEKDAYS.map((w) => (
                <div
                  key={w}
                  className="border-b border-r border-bc-line px-2 py-1 text-[12px] font-bold uppercase tracking-wider text-bc-subtle"
                >
                  {w}
                </div>
              ))}
              {days.map((d) => {
                const key = ymd(d);
                const inMonth = d.getMonth() === month.getMonth();
                const here = byDay.get(key);
                return (
                  <div
                    key={key}
                    onDoubleClick={() => setMaking(key)}
                    onDragOver={(ev) => {
                      if (ev.dataTransfer.types.includes('application/x-bc-day')) ev.preventDefault();
                    }}
                    onDrop={(ev) => {
                      const drag = ev.dataTransfer.getData('application/x-bc-day');
                      if (!drag) return;
                      ev.preventDefault();
                      void moveTo(drag, key).then(load, (err) =>
                        setError(apiErrorMessage(err, 'Could not move that.')),
                      );
                    }}
                    className={`min-h-24 border-b border-r border-bc-line p-1 ${key === today ? 'bg-bc-today' : ''}`}
                  >
                    <div className={`text-[13px] font-semibold ${inMonth ? '' : 'text-bc-faint'}`}>{d.getDate()}</div>
                    <div className="mt-0.5 space-y-0.5">
                      {here?.events.map((e) => eventChip(e, key))}
                      {here?.due.map(dueChip)}
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="mt-2 text-[13px] text-bc-faint">
              Double-click a day to add an event on it. Drag an event or something due to another day to move it.
            </p>
          </div>
        ) : (
          <ul className="mt-2">
            {[...byDay.entries()]
              .sort(([a], [b]) => (a < b ? -1 : 1))
              .filter(([k]) => k >= ymd(month))
              .map(([key, here]) => (
                <li key={key} className="flex gap-4 border-b border-bc-line py-3">
                  <div className={`w-16 shrink-0 rounded-lg py-1 text-center ${key === today ? 'bg-bc-today' : ''}`}>
                    <div className="text-[12px] font-bold uppercase text-bc-blue">
                      {parse(key).toLocaleDateString('en-US', { month: 'short' })}
                    </div>
                    <div className="text-[24px] font-extrabold leading-none text-bc-blue">{parse(key).getDate()}</div>
                  </div>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-[13px] text-bc-subtle">{day(key)}</p>
                    {here.events.map((e) => (
                      <Link key={`${e.id}-${e.on}`} to={`/i/${e.id}`} className="block hover:underline">
                        <span className={e.highlighted ? 'font-bold' : ''}>{e.title}</span>
                        <span className="text-[14px] text-bc-subtle">
                          {' '}
                          {timeLabel(e) || 'all day'}
                          {!projectId ? ` · ${e.board_name}` : ''}
                        </span>
                      </Link>
                    ))}
                    {here.due.map((d) => (
                      <Link
                        key={`${d.kind}-${d.id}`}
                        to={dueLink(d)}
                        className="block text-[15px] text-bc-subtle hover:underline"
                      >
                        {d.kind === 'card' ? '▤' : '☐'} {d.title}{' '}
                        <span className="text-[13px]">due{!projectId ? ` · ${d.board_name}` : ''}</span>
                      </Link>
                    ))}
                  </div>
                </li>
              ))}
            {range && byDay.size === 0 && (
              <li className="py-6 text-center text-bc-subtle">Nothing on the calendar in these months.</li>
            )}
          </ul>
        )}
      </Perma>
    </ProjectsShell>
  );
}
