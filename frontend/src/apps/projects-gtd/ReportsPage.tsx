// Projects GTD — Reports (key 3), as Basecamp 5's: one page of report tiles,
// then each report across every project: Overdue (in four groups by how late),
// Upcoming, Unassigned, Added & completed, Someone's tasks, Someone's activity,
// Mission Control (every project's Needle) and the Hilltop View (every Hill
// Chart). The Lineup has its own page.
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { todayStr } from '../todo-gtd/util';
import {
  getHilltop,
  getMissionControl,
  getOverdue,
  getPersonTasks,
  getProgress,
  getUnassigned,
  getUpcoming,
  type DueItem,
  type MissionProject,
  type ReportItem,
} from './api';
import { dueLink } from './CalendarPage';
import { Hill } from './HillChart';
import { Gauge, NEEDLE } from './Needle';
import { ProjectsShell, usePeople } from './ProjectsShell';
import type { Card, HillChart, Item, Person } from './types';
import { AvatarStack, Crumbs, day, EmptyState, parseYmd, Perma, when, ymd } from './ui';

const REPORTS: [string, string, string][] = [
  ['overdue', 'Overdue tasks', 'Everything past its due date, grouped by how late it is.'],
  ['upcoming', 'Upcoming tasks', 'What is due in the next two weeks, day by day.'],
  ['unassigned', 'Unassigned tasks', 'Open to-dos and cards nobody has.'],
  ['progress', 'Tasks added & completed', 'What was added, and what got done, this week or any range.'],
  ['person', "Someone's tasks", 'One person’s open to-dos and cards, an AI tool’s too.'],
  ['mission-control', 'Mission Control', 'Every project’s status, and the ones that have gone quiet.'],
  ['hilltop', 'Hilltop View', 'Every project’s Hill Chart in one place.'],
];

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <ProjectsShell title={title}>
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Reports', to: '/reports' }, { label: title }]} />
        <h1 className="bc-title text-2xl">{title}</h1>
        {children}
      </Perma>
    </ProjectsShell>
  );
}

/** One line of a report: the thing, where it is, who has it, and its date. */
function Line({
  to,
  title,
  project,
  people,
  date,
  tone,
}: {
  to: string;
  title: string;
  project: string;
  people?: Person[];
  date?: string | null;
  tone?: string;
}) {
  return (
    <li className="flex items-center gap-3 border-b border-bc-line py-2.5">
      <Link to={to} className="min-w-0 flex-1 hover:underline">
        <span className="block truncate font-semibold">{title}</span>
        <span className="block truncate text-[13px] text-bc-subtle">{project}</span>
      </Link>
      {people && people.length > 0 && <AvatarStack people={people} size={22} />}
      {date && <span className={`shrink-0 text-[14px] ${tone ?? 'text-bc-subtle'}`}>{date}</span>}
    </li>
  );
}

const dueLine = (d: DueItem, tone?: string, label?: string) => (
  <Line
    key={`${d.kind}${d.id}`}
    to={dueLink(d)}
    title={`${d.kind === 'card' ? '▤ ' : ''}${d.title}`}
    project={d.board_name}
    people={d.assignees}
    date={label ?? day(d.on)}
    tone={tone}
  />
);
const cardLine = (c: Card) => (
  <Line
    key={`c${c.id}`}
    to={`/p/${c.board_id}/cards?card=${c.id}`}
    title={`▤ ${c.title}`}
    project={c.board_name ?? ''}
    people={c.assignees}
    date={c.due_date ? day(c.due_date) : null}
  />
);
const todoLine = (t: Item) => (
  <Line
    key={`t${t.id}`}
    to={`/i/${t.id}`}
    title={t.title}
    project={t.board_name}
    people={t.assignees}
    date={t.due_on ? day(t.due_on) : null}
  />
);

export function ReportsIndex() {
  return (
    <ProjectsShell title="Reports">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Reports' }]} />
        <h1 className="bc-title text-2xl">Reports</h1>
        <p className="text-center text-bc-subtle">Across every project. Key 3 opens this page.</p>
        <div className="mx-auto mt-6 grid max-w-3xl gap-3 sm:grid-cols-2">
          <Link to="/lineup" className="rounded-lg border border-bc-line p-4 hover:border-bc-faint">
            <span className="block font-bold">Timeline</span>
            <span className="block text-[14px] text-bc-subtle">Projects with dates on one timeline.</span>
          </Link>
          {REPORTS.map(([path, title, blurb]) => (
            <Link
              key={path}
              to={`/reports/${path}`}
              className="rounded-lg border border-bc-line p-4 hover:border-bc-faint"
            >
              <span className="block font-bold">{title}</span>
              <span className="block text-[14px] text-bc-subtle">{blurb}</span>
            </Link>
          ))}
          <Link to="/activity" className="rounded-lg border border-bc-line p-4 hover:border-bc-faint">
            <span className="block font-bold">Someone's activity</span>
            <span className="block text-[14px] text-bc-subtle">What one person, or one AI tool, did lately.</span>
          </Link>
        </div>
      </Perma>
    </ProjectsShell>
  );
}

function useLoad<T>(load: () => Promise<T>, deps: unknown[]): [T | null, string] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    load().then(setData, (e) => setError(apiErrorMessage(e, 'Could not load the report.')));
  }, deps);
  return [data, error];
}

function Overdue() {
  const [data, error] = useLoad(getOverdue, []);
  return (
    <Shell title="Overdue tasks">
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      {data && data.count === 0 && (
        <div className="mt-6">
          <EmptyState title="Nothing is overdue. 🎉" />
        </div>
      )}
      {data?.groups
        .filter((g) => g.items.length)
        .map((g) => (
          <section key={g.label} className="mt-6">
            <h2 className="text-[13px] font-bold uppercase tracking-wider text-bc-unread">
              {g.label} ({g.items.length})
            </h2>
            <ul>
              {g.items.map((d) =>
                dueLine(d, 'text-bc-unread', `${d.days_late} day${d.days_late === 1 ? '' : 's'} late`),
              )}
            </ul>
          </section>
        ))}
    </Shell>
  );
}

function Upcoming() {
  const [days, setDays] = useState(14);
  const [data, error] = useLoad(() => getUpcoming(days), [days]);
  const byDay = new Map<string, DueItem[]>();
  for (const d of data?.items ?? []) byDay.set(d.on, [...(byDay.get(d.on) ?? []), d]);
  return (
    <Shell title="Upcoming tasks">
      <p className="text-center">
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          aria-label="How far ahead"
          className="bc-input w-auto py-1"
        >
          {[7, 14, 30, 60, 90].map((n) => (
            <option key={n} value={n}>
              Next {n} days
            </option>
          ))}
        </select>
      </p>
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      {data && !data.items.length && (
        <div className="mt-6">
          <EmptyState title="Nothing is due in that time." />
        </div>
      )}
      {[...byDay.entries()].map(([on, items]) => (
        <section key={on} className="mt-6">
          <h2
            className={`text-[13px] font-bold uppercase tracking-wider ${on === data?.today ? 'text-bc-blue' : 'text-bc-subtle'}`}
          >
            {on === data?.today ? 'Today' : day(on)}
          </h2>
          <ul>{items.map((d) => dueLine(d, undefined, ''))}</ul>
        </section>
      ))}
    </Shell>
  );
}

function Unassigned() {
  const [data, error] = useLoad(getUnassigned, []);
  return (
    <Shell title="Unassigned tasks">
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      {data && !data.todos.length && !data.cards.length && (
        <div className="mt-6">
          <EmptyState title="Everything open has someone on it." />
        </div>
      )}
      {data && data.todos.length > 0 && <ul className="mt-6">{data.todos.map(todoLine)}</ul>}
      {data && data.cards.length > 0 && (
        <section className="mt-6">
          <h2 className="text-[13px] font-bold uppercase tracking-wider text-bc-subtle">Cards</h2>
          <ul>{data.cards.map(cardLine)}</ul>
        </section>
      )}
    </Shell>
  );
}

function Progress() {
  const today = todayStr();
  const [start, setStart] = useState(() => ymd(new Date(parseYmd(today).getTime() - 6 * 86_400_000)));
  const [end, setEnd] = useState(today);
  const [data, error] = useLoad(() => getProgress(start, end), [start, end]);
  const line = (i: ReportItem, at: string | null | undefined) => (
    <Line
      key={`${i.type}${i.id}`}
      to={i.type === 'card' ? `/p/${i.board_id}/cards?card=${i.id}` : `/i/${i.id}`}
      title={`${i.type === 'card' ? '▤ ' : ''}${i.title}`}
      project={i.board_name}
      people={i.assignees}
      date={at ? when(at) : null}
    />
  );
  return (
    <Shell title="Tasks added & completed">
      <p className="flex flex-wrap items-center justify-center gap-2">
        <input
          type="date"
          value={start}
          max={end}
          onChange={(e) => e.target.value && setStart(e.target.value)}
          aria-label="From"
          className="bc-input w-auto py-1"
        />
        <span>to</span>
        <input
          type="date"
          value={end}
          min={start}
          onChange={(e) => e.target.value && setEnd(e.target.value)}
          aria-label="To"
          className="bc-input w-auto py-1"
        />
      </p>
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      {data && (
        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          <section>
            <h2 className="font-bold">Added ({data.added.length})</h2>
            <ul>{data.added.map((i) => line(i, i.created_at))}</ul>
          </section>
          <section>
            <h2 className="font-bold text-bc-green">Completed ({data.completed.length})</h2>
            <ul>{data.completed.map((i) => line(i, i.completed_at))}</ul>
          </section>
        </div>
      )}
    </Shell>
  );
}

function PersonTasks() {
  const { people } = usePeople();
  const navigate = useNavigate();
  const id = Number(useParams().person) || null;
  const [data, error] = useLoad(() => (id ? getPersonTasks(id) : Promise.resolve(null)), [id]);
  const byProject = new Map<string, (Item | Card)[]>();
  for (const t of [...(data?.todos ?? []), ...(data?.cards ?? [])]) {
    const name = t.board_name ?? '';
    byProject.set(name, [...(byProject.get(name) ?? []), t]);
  }
  return (
    <Shell title={data ? `${data.person.name}'s tasks` : "Someone's tasks"}>
      <p className="text-center">
        <select
          value={id ?? ''}
          onChange={(e) => navigate(`/reports/person/${e.target.value}`)}
          aria-label="Whose"
          className="bc-input w-auto py-1"
        >
          <option value="">Pick someone…</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {p.kind === 'ai' ? ' (AI)' : ''}
            </option>
          ))}
        </select>
        {id && (
          <Link to={`/activity?person=${id}`} className="ml-3 text-[15px] text-bc-blue underline">
            Their activity
          </Link>
        )}
      </p>
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      {data && byProject.size === 0 && (
        <div className="mt-6">
          <EmptyState title="Nothing open is assigned to them." />
        </div>
      )}
      {[...byProject.entries()].map(([project, items]) => (
        <section key={project} className="mt-6">
          <h2 className="font-bold">{project}</h2>
          <ul>{items.map((t) => ('column_id' in t ? cardLine(t as Card) : todoLine(t as Item)))}</ul>
        </section>
      ))}
    </Shell>
  );
}

function MissionControl() {
  const [projects, error] = useLoad(getMissionControl, []);
  const row = (p: MissionProject) => (
    <li key={p.id} className="flex items-center gap-3 border-b border-bc-line py-3">
      <Gauge value={p.needle?.needle} size={48} />
      <Link to={`/p/${p.id}`} className="min-w-0 flex-1 hover:underline">
        <span className="block truncate font-bold">{p.name}</span>
        <span className="block truncate text-[14px] text-bc-subtle">
          {p.needle?.needle
            ? `${NEEDLE[p.needle.needle].label} · ${when(p.needle.created_at)}${p.needle.body ? ` · “${p.needle.body}”` : ''}`
            : 'No status yet'}
        </span>
      </Link>
      <span className={`shrink-0 text-[13px] ${p.quiet ? 'font-bold text-bc-unread' : 'text-bc-subtle'}`}>
        {p.quiet ? 'Gone quiet' : p.last_activity_at ? `Active ${when(p.last_activity_at)}` : ''}
      </span>
    </li>
  );
  return (
    <Shell title="Mission Control">
      <p className="text-center text-bc-subtle">
        Every project's status. A project nothing has touched in two weeks has gone quiet.
      </p>
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      <ul className="mt-4">{projects?.map(row)}</ul>
    </Shell>
  );
}

function Hilltop() {
  const [projects, error] = useLoad(getHilltop, []);
  return (
    <Shell title="Hilltop View">
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      {projects && !projects.length && (
        <div className="mt-6">
          <EmptyState title="No Hill Charts yet.">Track a project's to-do lists on its To-dos page.</EmptyState>
        </div>
      )}
      <div className="mt-6 grid gap-6 sm:grid-cols-2">
        {projects?.map((p: HillChart & { id: number; name: string }) => (
          <Link
            key={p.id}
            to={`/p/${p.id}/todos`}
            className="rounded-lg border border-bc-line p-3 hover:border-bc-faint"
          >
            <span className="block font-bold">{p.name}</span>
            <span className={`block text-[13px] ${p.stale ? 'text-bc-unread' : 'text-bc-subtle'}`}>
              {p.stale ? "It's been a while" : p.updated_at ? `Updated ${when(p.updated_at)}` : ''}
            </span>
            <Hill lists={p.lists} small />
            <span className="block text-[13px] text-bc-subtle">{p.lists.map((l) => l.title).join(' · ')}</span>
          </Link>
        ))}
      </div>
    </Shell>
  );
}

export function ReportPage() {
  const kind = useParams().kind;
  if (kind === 'overdue') return <Overdue />;
  if (kind === 'upcoming') return <Upcoming />;
  if (kind === 'unassigned') return <Unassigned />;
  if (kind === 'progress') return <Progress />;
  if (kind === 'person') return <PersonTasks />;
  if (kind === 'mission-control') return <MissionControl />;
  if (kind === 'hilltop') return <Hilltop />;
  return <ReportsIndex />;
}

export { PersonTasks };
