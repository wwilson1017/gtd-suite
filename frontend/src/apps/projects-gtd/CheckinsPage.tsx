// Projects GTD — Automatic Check-ins (a question asked on a schedule, of you and
// your AI tools, answered day by day) and the Lineup (projects with dates, as
// bars across thirteen weeks with today in the middle).
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { todayStr } from '../todo-gtd/util';
import { createItem, getLineup, getProject, listItems, updateBoard, type LineupProject } from './api';
import { ProjectsShell, usePeople } from './ProjectsShell';
import type { Item, Project } from './types';
import { AvatarStack, Crumbs, EmptyState, Perma, day, parseYmd as parse, ymd } from './ui';

const WEEKDAY_LETTERS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
const FREQ: Record<string, string> = {
  every_day: 'every',
  every_week: 'every week on',
  every_other_week: 'every other week on',
  every_month: 'once a month',
};

/** "Asked every Mo, Tu, We, Th, Fr at 9:00am" — the schedule in words. */
export function scheduleText(q: Item): string {
  if (q.paused) return 'Paused: not asking anyone';
  const [h, m] = (q.time ?? '09:00').split(':').map(Number);
  const at = `${h % 12 || 12}${m ? `:${String(m).padStart(2, '0')}` : ''}${h < 12 ? 'am' : 'pm'}`;
  const picked = [...(q.days ?? [])].sort();
  const days =
    picked.length === 7
      ? 'day'
      : picked.join() === '1,2,3,4,5'
        ? 'weekday'
        : picked.map((d) => WEEKDAY_LETTERS[d]).join(', ');
  if (q.frequency === 'every_month') return `Asked once a month at ${at}`;
  const which = q.frequency === 'every_day' ? days : WEEKDAY_LETTERS[(q.days ?? [1])[0]];
  return `Asked ${FREQ[q.frequency ?? 'every_day']} ${which} at ${at}`;
}

function NewQuestion({ projectId, onDone }: { projectId: number; onDone: (made: boolean) => void }) {
  const { people } = usePeople();
  const [title, setTitle] = useState('');
  const [frequency, setFrequency] = useState('every_day');
  const [days, setDays] = useState<number[]>([1, 2, 3, 4, 5]);
  const [time, setTime] = useState('09:00');
  const [asked, setAsked] = useState<(number | string)[]>(['me']);
  const [error, setError] = useState('');
  const save = async () => {
    try {
      await createItem(projectId, 'question', { title: title.trim(), frequency, days, time, assignee_ids: asked });
      onDone(true);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save the question.'));
    }
  };
  const toggle = (d: number) =>
    setDays((ds) => (frequency === 'every_day' ? (ds.includes(d) ? ds.filter((x) => x !== d) : [...ds, d]) : [d]));
  return (
    <form
      className="mt-4 rounded-lg border border-bc-line p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <p className="font-bold">New question</p>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        maxLength={500}
        aria-label="Question"
        placeholder="What did you work on today?"
        className="bc-input mt-2 text-[18px] font-bold"
      />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[15px]">
        <span>Ask</span>
        <select
          value={frequency}
          onChange={(e) => {
            setFrequency(e.target.value);
            if (e.target.value !== 'every_day') setDays((d) => [d[0] ?? 1]);
          }}
          aria-label="How often"
          className="bc-input w-auto py-1"
        >
          <option value="every_day">on these days</option>
          <option value="every_week">every week on</option>
          <option value="every_other_week">every other week on</option>
          <option value="every_month">once a month</option>
        </select>
        {frequency !== 'every_month' &&
          WEEKDAY_LETTERS.map((w, d) => (
            <button
              key={w}
              type="button"
              aria-pressed={days.includes(d)}
              onClick={() => toggle(d)}
              className={`h-8 w-8 rounded-full border text-[13px] ${days.includes(d) ? 'border-bc-blue bg-bc-highlight font-bold' : 'border-bc-line'}`}
            >
              {w}
            </button>
          ))}
        <span>at</span>
        <input
          type="time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
          aria-label="Time"
          className="bc-input w-auto py-1"
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[15px]">
        <span>Who's asked:</span>
        {(people.length ? people : [{ id: 0, name: 'Me', kind: 'me' as const, color: '' }]).map((p) => {
          const value = p.kind === 'me' ? 'me' : p.id;
          const on = asked.includes(value);
          return (
            <button
              key={p.id}
              type="button"
              aria-pressed={on}
              onClick={() => setAsked((a) => (on ? a.filter((x) => x !== value) : [...a, value]))}
              className={`rounded-full border px-3 py-0.5 ${on ? 'border-bc-blue bg-bc-highlight' : 'border-bc-line'}`}
            >
              {p.name}
              {p.kind === 'ai' ? ' (AI)' : ''}
            </button>
          );
        })}
      </div>
      {error && (
        <p role="alert" className="mt-1 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          className="bc-btn bc-btn-primary"
          disabled={!title.trim() || !asked.length || !days.length}
        >
          Start asking this question
        </button>
        <button type="button" className="bc-btn" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function CheckinsPage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [questions, setQuestions] = useState<Item[] | null>(null);
  const [making, setMaking] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    listItems(id, 'question').then(setQuestions, (e) => setError(apiErrorMessage(e, 'Could not load the check-ins.')));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    getProject(id).then(setProject, () => {});
  }, [id]);
  const title = project?.dock.find((t) => t.tool === 'questionnaire')?.title ?? 'Check-ins';
  return (
    <ProjectsShell project={project} title={`${title} · ${project?.name ?? ''}`}>
      <Perma>
        <Crumbs project={project} crumbs={[{ label: project?.name ?? '…', to: `/p/${id}` }, { label: title }]} />
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="bc-title mr-auto text-2xl">{title}</h1>
          <button type="button" className="bc-btn bc-btn-primary" onClick={() => setMaking(true)}>
            ＋ New question
          </button>
        </div>
        <p className="mt-1 text-bc-subtle">
          Ask on a schedule — you, your AI tools, anyone — and keep the answers together, day by day.
        </p>
        {making && (
          <NewQuestion
            projectId={id}
            onDone={(made) => {
              setMaking(false);
              if (made) load();
            }}
          />
        )}
        {error && (
          <p role="alert" className="mt-3 text-bc-unread">
            {error}
          </p>
        )}
        {questions && questions.length === 0 && !making && (
          <div className="mt-6">
            <EmptyState title="No check-ins yet.">
              "What did you work on today?" every weekday at 4:30 is a good start.
            </EmptyState>
          </div>
        )}
        <ul className="mt-6">
          {questions?.map((q) => (
            <li key={q.id} className="border-b border-bc-line">
              <Link to={`/i/${q.id}`} className="flex items-center gap-3 py-4 hover:bg-bc-wash sm:px-2">
                <span aria-hidden className="text-2xl">
                  💬
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[18px] font-bold">{q.title}</span>
                  <span className="block text-[14px] text-bc-subtle">{scheduleText(q)}</span>
                </span>
                <AvatarStack people={q.assignees} size={24} />
              </Link>
            </li>
          ))}
        </ul>
      </Perma>
    </ProjectsShell>
  );
}

// ── The Lineup ────────────────────────────────────────────────────────────────

export function LineupPage() {
  const today = parse(todayStr());
  const [center, setCenter] = useState(today);
  const [projects, setProjects] = useState<LineupProject[] | null>(null);
  const start = useMemo(
    () => new Date(center.getFullYear(), center.getMonth(), center.getDate() - 42 - center.getDay()),
    [center],
  );
  const end = useMemo(() => new Date(start.getFullYear(), start.getMonth(), start.getDate() + 13 * 7 - 1), [start]);
  useEffect(() => {
    getLineup(ymd(start), ymd(end)).then(setProjects, () => setProjects([]));
  }, [start, end]);
  const span = (end.getTime() - start.getTime()) / 86_400_000 + 1;
  const pct = (d: Date) => Math.max(0, Math.min(100, ((d.getTime() - start.getTime()) / 86_400_000 / span) * 100));
  const weeks = Array.from(
    { length: 13 },
    (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i * 7),
  );
  const move = (n: number) => setCenter((c) => new Date(c.getFullYear(), c.getMonth(), c.getDate() + n * 7));
  return (
    <ProjectsShell title="Lineup">
      <Perma wide>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Timeline' }]} />
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="bc-title mr-auto text-2xl">Timeline</h1>
          <button type="button" className="bc-btn bc-btn-sm" onClick={() => move(-6)}>
            ← Prev 6 weeks
          </button>
          <button type="button" className="bc-btn bc-btn-sm" onClick={() => setCenter(today)}>
            Today
          </button>
          <button type="button" className="bc-btn bc-btn-sm" onClick={() => move(6)}>
            Next 6 weeks →
          </button>
        </div>
        <div className="relative mt-4 overflow-x-auto">
          <div className="relative min-w-[760px]">
            <div
              className="grid grid-cols-13 border-b border-bc-line"
              style={{ gridTemplateColumns: 'repeat(13, minmax(0, 1fr))' }}
            >
              {weeks.map((w) => (
                <div key={ymd(w)} className="border-l border-bc-line px-1 py-1 text-[12px] text-bc-subtle">
                  {w.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                </div>
              ))}
            </div>
            <div
              className="absolute bottom-0 top-0 w-0.5 bg-bc-blue"
              style={{ left: `${pct(today)}%` }}
              aria-label="Today"
            />
            <ul className="space-y-2 py-3">
              {projects?.map((p) => {
                const left = pct(parse(p.starts_on));
                const right = pct(new Date(parse(p.ends_on).getTime() + 86_400_000));
                const now = p.starts_on <= ymd(today) && ymd(today) <= p.ends_on;
                return (
                  <li key={p.id} className="relative h-12">
                    <Link
                      to={`/p/${p.id}`}
                      title={`${p.name}: ${day(p.starts_on)} – ${day(p.ends_on)}`}
                      className={`absolute top-0 flex h-12 items-center overflow-hidden rounded-lg border px-3 text-[15px] font-bold hover:border-bc-ink ${now ? 'border-bc-line bg-bc-canvas shadow' : 'border-dashed border-bc-line bg-bc-wash text-bc-subtle'}`}
                      style={{ left: `${left}%`, width: `${Math.max(right - left, 4)}%` }}
                    >
                      <span className="truncate">{p.name}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
        {projects && projects.length === 0 && (
          <EmptyState title="No projects with dates in these weeks.">
            Give a project a start and an end from its ••• menu (Set dates), and it lines up here.
          </EmptyState>
        )}
      </Perma>
    </ProjectsShell>
  );
}

/** Set a project's dates (Lineup), from its ••• menu. */
export function DatesEditor({ project, onDone }: { project: Project; onDone: () => void }) {
  const [starts, setStarts] = useState(project.starts_on ?? '');
  const [ends, setEnds] = useState(project.ends_on ?? '');
  const [error, setError] = useState('');
  return (
    <form
      className="mx-auto mt-4 flex max-w-xl flex-wrap items-center gap-2 rounded-lg bg-bc-wash p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void updateBoard(project.id, { starts_on: starts || null, ends_on: ends || null }).then(onDone, (err) =>
          setError(apiErrorMessage(err, 'Could not save the dates.')),
        );
      }}
    >
      <span className="font-semibold">Project dates</span>
      <input
        type="date"
        value={starts}
        onChange={(e) => setStarts(e.target.value)}
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
      <button type="submit" className="bc-btn bc-btn-primary bc-btn-sm">
        Save
      </button>
      <button type="button" className="bc-btn bc-btn-sm" onClick={onDone}>
        Cancel
      </button>
      {error && (
        <p role="alert" className="w-full text-sm text-bc-unread">
          {error}
        </p>
      )}
    </form>
  );
}
