// Projects GTD — one item's page, as Basecamp draws them all: the breadcrumb row
// with Bookmark and •••, a big heavy title, the line saying who and when, the body
// hung beside its writer's avatar, boosts, then the comments. A to-do adds its
// fields (assigned to, dates, notes, subtasks); a to-do list its to-dos and groups;
// an event its dates and repeat; a check-in question its schedule and the answers
// day by day; a link the address it points at.
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import {
  boostItem,
  bubbleUp,
  commentOn,
  completeItem,
  createItem,
  getAnswers,
  getItem,
  getMuted,
  getProject,
  removeBoost,
  setBookmark,
  setMuted,
  updateItem,
  type ItemFields,
} from './api';
import { REPEATS } from './CalendarPage';
import { MoveCopyDialog } from './MoveCopy';
import { scheduleText } from './CheckinsPage';
import { CATEGORIES } from './MessageBoardPage';
import { ProjectsShell, usePeople } from './ProjectsShell';
import { todayStr } from '../todo-gtd/util';
import { AddTodo, changeDates, CompletedToggle, dropTodo, TodoRow } from './TodosPage';
import type { Item, Person, Project, Thread, Tool } from './types';
import {
  Avatar,
  Body,
  Boosts,
  ColorPicker,
  Comments,
  Crumbs,
  day,
  Menu,
  on,
  Perma,
  ProgressPie,
  TOOL_PATH,
  when,
  type Crumb,
} from './ui';

const TOOL_OF: Partial<Record<Item['type'], Tool>> = {
  message: 'message_board',
  todolist: 'todoset',
  todolist_group: 'todoset',
  todo: 'todoset',
  step: 'todoset',
  vault: 'vault',
  document: 'vault',
  link: 'vault',
  schedule_entry: 'schedule',
  question: 'questionnaire',
  answer: 'questionnaire',
  chat_line: 'chat',
  door: 'doors',
  wormhole: 'kanban_board',
};

const TOOL_NAME: Record<Tool, string> = {
  message_board: 'Messages',
  todoset: 'To-dos',
  vault: 'Docs',
  schedule: 'Calendar',
  questionnaire: 'Check-ins',
  kanban_board: 'Board',
  chat: 'Chat',
  doors: 'External links',
};

const LABEL: Record<Item['type'], string> = {
  message: 'message',
  todolist: 'to-do list',
  todolist_group: 'group',
  todo: 'to-do',
  step: 'subtask',
  comment: 'comment',
  vault: 'folder',
  document: 'document',
  link: 'link',
  schedule_entry: 'event',
  question: 'question',
  answer: 'answer',
  needle: 'Status update',
  hill_update: 'Hill Chart update',
  chat_line: 'chat line',
  door: 'external link',
  wormhole: 'wormhole',
};

// What can be moved and copied (a subtask, comment or answer stays where it is).
const MOVABLE = new Set<Item['type']>([
  'message',
  'todolist',
  'todolist_group',
  'todo',
  'vault',
  'document',
  'link',
  'schedule_entry',
  'question',
]);

// What the person can put in the project page's Spotlight.
const SPOTLIGHTABLE = new Set<Item['type']>([
  'message',
  'todolist',
  'todo',
  'vault',
  'document',
  'link',
  'schedule_entry',
  'question',
]);

// The types whose page centres its title over a body, as Basecamp draws a message.
const CENTRED = new Set<Item['type']>(['message', 'document', 'answer']);

function PeoplePicker({ value, onChange }: { value: Person[]; onChange: (ids: (number | string)[]) => void }) {
  const { people } = usePeople();
  const ids = value.map((p) => p.id);
  const others = people.filter((p) => !ids.includes(p.id));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {value.map((p) => (
        <span
          key={p.id}
          className="inline-flex items-center gap-1 rounded-full bg-bc-wash py-0.5 pl-0.5 pr-2 text-[15px]"
        >
          <Avatar person={p} size={22} />
          {p.name}
          <button
            type="button"
            aria-label={`Unassign ${p.name}`}
            className="ml-0.5 text-bc-faint hover:text-bc-ink"
            onClick={() => onChange(ids.filter((i) => i !== p.id))}
          >
            ×
          </button>
        </span>
      ))}
      <select
        value=""
        aria-label="Assign someone"
        className="bc-input w-auto py-1 text-[15px]"
        onChange={(e) => {
          if (e.target.value) onChange([...ids, e.target.value === 'me' ? 'me' : Number(e.target.value)]);
        }}
      >
        <option value="">{value.length ? 'Add someone…' : 'Type names to assign…'}</option>
        {people.length === 0 && <option value="me">Me</option>}
        {others.map((p) => (
          <option key={p.id} value={p.kind === 'me' ? 'me' : p.id}>
            {p.name}
            {p.kind === 'ai' ? ' (AI)' : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-bc-line py-3 sm:grid-cols-[9rem_1fr] sm:gap-4">
      <div className="text-[15px] font-bold sm:text-right">{label}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** A to-do's subtasks: each checks off on its own. */
function Subtasks({ todo, steps, reload }: { todo: Item; steps: Item[]; reload: () => void }) {
  const [title, setTitle] = useState('');
  const add = async () => {
    if (!title.trim()) return;
    await createItem(todo.board_id, 'step', { title: title.trim() }, { parent_id: todo.id });
    setTitle('');
    reload();
  };
  return (
    <div>
      <ul className="space-y-1">
        {steps.map((s) => (
          <li key={s.id} className="flex items-center gap-2">
            <input
              type="checkbox"
              className="bc-checkbox"
              checked={s.completed}
              aria-label={`Subtask ${s.title}`}
              onChange={() => void completeItem(s.id, !s.completed).then(reload)}
            />
            <span className={s.completed ? 'text-bc-subtle line-through' : ''}>{s.title}</span>
            {s.assignees.length > 0 && (
              <span className="text-[13px] text-bc-subtle">{s.assignees.map((a) => a.name).join(', ')}</span>
            )}
            {s.due_on && <span className="text-[13px] text-bc-subtle">· {day(s.due_on)}</span>}
          </li>
        ))}
      </ul>
      <form
        className="mt-1.5 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
      >
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Add a subtask…"
          aria-label="New subtask"
          maxLength={500}
          className="bc-input py-1 text-[15px]"
        />
        <button type="submit" className="bc-btn bc-btn-sm" disabled={!title.trim()}>
          Add
        </button>
      </form>
    </div>
  );
}

function EditForm({
  item,
  onSave,
  onCancel,
}: {
  item: Item;
  onSave: (fields: ItemFields) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(item.title);
  const [body, setBody] = useState(item.body);
  const [category, setCategory] = useState(item.category);
  const [color, setColor] = useState(item.color);
  const [url, setUrl] = useState(item.url ?? '');
  const fields: ItemFields = item.type === 'answer' ? {} : { title: title.trim() };
  if (item.type !== 'todolist_group' && item.type !== 'question') fields.body = body;
  if (item.type === 'message') fields.category = category;
  if (['todolist', 'todolist_group', 'document', 'link'].includes(item.type)) fields.color = color;
  if (item.type === 'link' || item.type === 'door' || item.type === 'schedule_entry') fields.url = url.trim();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void onSave(fields);
      }}
    >
      {item.type === 'message' && (
        <div className="mb-3 flex flex-wrap gap-2">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={category === c}
              onClick={() => setCategory(category === c ? '' : c)}
              className={`rounded-full border px-3 py-1 text-[14px] ${category === c ? 'border-bc-blue bg-bc-highlight' : 'border-bc-line'}`}
            >
              {c}
            </button>
          ))}
        </div>
      )}
      {item.type !== 'answer' && (
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="Title"
          maxLength={500}
          className="bc-input bc-title text-[26px]"
        />
      )}
      {(item.type === 'link' || item.type === 'door' || item.type === 'schedule_entry') && (
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          aria-label={item.type === 'schedule_entry' ? 'Join link' : 'Address'}
          maxLength={500}
          placeholder={item.type === 'schedule_entry' ? 'Join link (Zoom, Meet…), optional' : ''}
          className="bc-input mt-3"
        />
      )}
      {item.type !== 'todolist_group' && item.type !== 'question' && (
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          aria-label="Body"
          rows={item.type === 'message' || item.type === 'document' ? 12 : 5}
          maxLength={20000}
          placeholder="Markdown works"
          className="bc-input mt-3 text-[17px]"
        />
      )}
      {['todolist', 'todolist_group', 'document', 'link'].includes(item.type) && (
        <div className="mt-3">
          <ColorPicker value={color} onChange={setColor} />
        </div>
      )}
      <div className="sticky top-2 mt-3 flex gap-2">
        <button type="submit" className="bc-btn bc-btn-primary" disabled={item.type !== 'answer' && !title.trim()}>
          Save changes
        </button>
        <button type="button" className="bc-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** An event's when, repeat, join link and circle, each saved as it changes. */
function EventFields({ item, save }: { item: Item; save: (f: ItemFields) => void }) {
  return (
    <>
      <Field label="When">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={item.starts_on ?? ''}
            aria-label="Starts"
            className="bc-input w-auto py-1"
            onChange={(e) =>
              e.target.value &&
              save({
                starts_on: e.target.value,
                ...(item.due_on && item.due_on < e.target.value ? { ends_on: e.target.value } : {}),
              })
            }
          />
          <span className="text-bc-subtle">to</span>
          <input
            type="date"
            value={item.due_on ?? ''}
            min={item.starts_on ?? undefined}
            aria-label="Ends"
            className="bc-input w-auto py-1"
            onChange={(e) => save({ ends_on: e.target.value || null })}
          />
          <label className="flex items-center gap-1.5 text-[15px]">
            <input
              type="checkbox"
              className="bc-checkbox"
              checked={item.all_day ?? true}
              onChange={(e) =>
                save(
                  e.target.checked
                    ? { all_day: true, starts_at: null, ends_at: null }
                    : { all_day: false, starts_at: '09:00', ends_at: '10:00' },
                )
              }
            />
            All day
          </label>
          {!item.all_day && (
            <>
              <input
                type="time"
                value={item.starts_at ?? ''}
                aria-label="From"
                className="bc-input w-auto py-1"
                onChange={(e) => save({ starts_at: e.target.value || null })}
              />
              <span>–</span>
              <input
                type="time"
                value={item.ends_at ?? ''}
                aria-label="Until"
                className="bc-input w-auto py-1"
                onChange={(e) => save({ ends_at: e.target.value || null })}
              />
            </>
          )}
        </div>
      </Field>
      <Field label="Repeats">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={item.repeat ?? ''}
            aria-label="Repeat"
            className="bc-input w-auto py-1"
            onChange={(e) => save({ repeat: e.target.value || null })}
          >
            {REPEATS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          {item.repeat && (
            <>
              <span className="text-bc-subtle">until</span>
              <input
                type="date"
                value={item.repeat_until ?? ''}
                aria-label="Repeat until"
                className="bc-input w-auto py-1"
                onChange={(e) => save({ repeat_until: e.target.value || null })}
              />
            </>
          )}
        </div>
      </Field>
      <Field label="Join link">
        {item.url ? (
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="break-all text-bc-blue underline">
            {item.url}
          </a>
        ) : (
          <span className="text-[15px] text-bc-faint">None. Edit the event to add a Zoom or Meet link.</span>
        )}
      </Field>
      <Field label="Circled">
        <label className="flex items-center gap-1.5 text-[15px]">
          <input
            type="checkbox"
            className="bc-checkbox"
            checked={!!item.highlighted}
            onChange={(e) => save({ highlighted: e.target.checked })}
          />
          Circle it on the calendar
        </label>
      </Field>
    </>
  );
}

/** A check-in question: its schedule, who's asked, Answer, and the answers day by day. */
function QuestionView({ item, save, reload }: { item: Item; save: (f: ItemFields) => void; reload: () => void }) {
  const { me } = usePeople();
  const [days, setDays] = useState<{ day: string; answers: Item[] }[]>([]);
  const [answering, setAnswering] = useState(false);
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const loadAnswers = useCallback(() => {
    getAnswers(item.id).then(setDays, () => {});
  }, [item.id]);
  useEffect(loadAnswers, [loadAnswers]);
  const today = todayStr();
  const answeredToday = days.some((d) => d.day === today && d.answers.some((a) => a.creator?.id === me?.id));
  const post = async () => {
    try {
      // The server dates the answer: today in the account's time zone.
      await createItem(item.board_id, 'answer', { body }, { parent_id: item.id });
      setBody('');
      setAnswering(false);
      loadAnswers();
      reload();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not post the answer.'));
    }
  };
  return (
    <div className="mt-4">
      <Field label="Schedule">
        <div className="flex flex-wrap items-center gap-2">
          <span>{scheduleText(item)}</span>
          <button type="button" className="bc-btn bc-btn-sm" onClick={() => save({ paused: !item.paused })}>
            {item.paused ? 'Resume asking' : 'Pause'}
          </button>
          {!item.paused && (
            <input
              type="time"
              value={item.time ?? '09:00'}
              aria-label="Time"
              className="bc-input w-auto py-1"
              onChange={(e) => e.target.value && save({ time: e.target.value })}
            />
          )}
        </div>
      </Field>
      <Field label="Who's asked">
        <PeoplePicker value={item.assignees} onChange={(ids) => save({ assignee_ids: ids })} />
      </Field>
      <div className="mt-6">
        {answering ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void post();
            }}
          >
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              autoFocus
              rows={5}
              maxLength={20000}
              aria-label="Your answer"
              placeholder="Type your answer… (Markdown works)"
              className="bc-input text-[17px]"
            />
            {error && (
              <p role="alert" className="mt-1 text-sm text-bc-unread">
                {error}
              </p>
            )}
            <div className="mt-2 flex gap-2">
              <button type="submit" className="bc-btn bc-btn-primary" disabled={!body.trim()}>
                Post this answer
              </button>
              <button type="button" className="bc-btn" onClick={() => setAnswering(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <button type="button" className="bc-btn bc-btn-primary" onClick={() => setAnswering(true)}>
            {answeredToday ? 'Add another answer' : 'Answer this question'}
          </button>
        )}
      </div>
      {days.length === 0 && <p className="mt-6 text-bc-subtle">No answers yet.</p>}
      {days.map((d) => (
        <section key={d.day} className="mt-8">
          <h2 className="border-b border-bc-line pb-1 text-center text-[13px] font-bold uppercase tracking-wider text-bc-subtle">
            {day(d.day)}
          </h2>
          <ul>
            {d.answers.map((a) => (
              <li key={a.id} id={`answer-${a.id}`} className="flex gap-3 border-b border-bc-line py-4">
                <Avatar person={a.creator} size={36} />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] text-bc-subtle">
                    <b className="text-bc-ink">{a.creator?.name}</b> · {when(a.created_at)}
                  </p>
                  <Body text={a.body} />
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <Boosts
                      boosts={a.boosts ?? []}
                      onBoost={(c) => boostItem(a.id, c).then(loadAnswers)}
                      onRemove={(b) => removeBoost(b).then(loadAnswers)}
                    />
                    <Link to={`/i/${a.id}`} className="text-[14px] text-bc-blue hover:underline">
                      {a.comments_count ? `${a.comments_count} comment${a.comments_count === 1 ? '' : 's'}` : 'Comment'}
                    </Link>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function ItemPage() {
  const id = Number(useParams().id);
  const [thread, setThread] = useState<Thread | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [editing, setEditing] = useState(false);
  const [moving, setMoving] = useState<'move' | 'copy' | null>(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [quietHere, setQuietHere] = useState(false); // "Don't notify me" on this item
  useEffect(() => {
    getMuted({ item_id: id }).then(setQuietHere, () => {});
  }, [id]);
  const { me, reload: reloadPeople } = usePeople();
  const navigate = useNavigate();

  const load = useCallback(() => {
    getItem(id).then(
      (t) => {
        // A comment or a subtask has no page of its own: show the thing it sits on.
        if (t.recording.type === 'comment' || t.recording.type === 'step') {
          if (t.recording.parent_id)
            navigate(`/i/${t.recording.parent_id}${t.recording.type === 'comment' ? `#comment-${id}` : ''}`, {
              replace: true,
            });
          else if (t.recording.card_id)
            navigate(`/p/${t.recording.board_id}/cards?card=${t.recording.card_id}`, { replace: true });
          return;
        }
        if (t.recording.type === 'vault') {
          navigate(`/p/${t.recording.board_id}/docs?folder=${id}`, { replace: true });
          return;
        }
        // The Needle and Hill Chart updates live on the project page and the To-dos page.
        if (t.recording.type === 'chat_line') {
          navigate(`/p/${t.recording.board_id}/chat`, { replace: true });
          return;
        }
        if (t.recording.type === 'needle' || t.recording.type === 'hill_update') {
          navigate(`/p/${t.recording.board_id}${t.recording.type === 'hill_update' ? '/todos' : ''}`, {
            replace: true,
          });
          return;
        }
        setThread(t);
        getProject(t.recording.board_id).then(setProject, () => {});
      },
      (e) => setError(apiErrorMessage(e, 'Could not load this.')),
    );
  }, [id, navigate]);
  useEffect(load, [load]);

  if (error)
    return (
      <ProjectsShell>
        <Perma>
          <p role="alert" className="text-bc-unread">
            {error}
          </p>
        </Perma>
      </ProjectsShell>
    );
  if (!thread)
    return (
      <ProjectsShell>
        <Perma>
          <p className="text-bc-subtle">Loading…</p>
        </Perma>
      </ProjectsShell>
    );

  const item = thread.recording;
  const tool = TOOL_OF[item.type];
  const toolEntry = project?.dock.find((t) => t.tool === tool);
  const crumbs: Crumb[] = [{ label: item.board_name, to: `/p/${item.board_id}` }];
  if (tool) crumbs.push({ label: toolEntry?.title ?? TOOL_NAME[tool], to: `/p/${item.board_id}/${TOOL_PATH[tool]}` });
  for (const a of thread.ancestors) crumbs.push({ label: a.title, to: `/i/${a.id}` });

  const save = async (fields: ItemFields) => {
    try {
      await updateItem(id, { ...fields, version: item.version });
      setEditing(false);
      setNote('');
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setNote(
          'Someone (maybe your AI) changed this while you were editing. Your edit was not saved; here is the latest.',
        );
        setEditing(false);
        load();
      } else {
        setNote(apiErrorMessage(e, 'Could not save.'));
      }
    }
  };
  // A field saved as it changes (an event's dates, a question's schedule).
  const quick = async (fields: ItemFields) => {
    try {
      await updateItem(id, fields);
      load();
    } catch (e) {
      setNote(apiErrorMessage(e, 'Could not save that.'));
    }
  };
  const setStatus = async (status: Item['status'], message: string) => {
    await updateItem(id, { status });
    setNote(message);
    load();
  };
  const assign = async (ids: (number | string)[]) => {
    await updateItem(id, { assignee_ids: ids });
    reloadPeople();
    load();
  };
  const kids = thread.children ?? [];
  const isList = item.type === 'todolist' || item.type === 'todolist_group';

  return (
    <ProjectsShell title={item.title || LABEL[item.type]}>
      <Perma>
        <Crumbs
          crumbs={crumbs}
          right={
            <>
              <button
                type="button"
                className="bc-btn bc-btn-sm"
                onClick={() => void setBookmark({ item_id: id }, !item.bookmarked).then(load)}
              >
                🔖 {item.bookmarked ? 'Bookmarked' : 'Bookmark'}
              </button>
              {item.status !== 'trashed' && (
                <button type="button" className="bc-btn bc-btn-sm" onClick={() => setEditing(true)}>
                  Edit
                </button>
              )}
              <Menu
                items={[
                  { label: 'Copy link', onClick: () => void navigator.clipboard?.writeText(window.location.href) },
                  {
                    label: item.pinned_at ? 'Unpin' : 'Pin to the top of the board',
                    hidden: item.type !== 'message' || item.status !== 'active',
                    onClick: () =>
                      void updateItem(id, { pinned: !item.pinned_at })
                        .then(load)
                        .catch((e) => setNote(apiErrorMessage(e, 'Could not pin it.'))),
                  },
                  {
                    label: item.spotlight
                      ? 'Take it out of the Spotlight'
                      : 'Put it in the Spotlight (on the project page)',
                    hidden: !SPOTLIGHTABLE.has(item.type) || item.status !== 'active',
                    onClick: () =>
                      void updateItem(id, { spotlight: !item.spotlight })
                        .then(load)
                        .catch((e) => setNote(apiErrorMessage(e, 'Could not change the Spotlight.'))),
                  },
                  {
                    label: 'Change dates…',
                    hidden: !isList || item.status !== 'active',
                    onClick: () => void changeDates(id, load, setNote),
                  },
                  {
                    label: 'Move…',
                    hidden: !MOVABLE.has(item.type) || item.status !== 'active',
                    onClick: () => setMoving('move'),
                  },
                  {
                    label: 'Copy…',
                    hidden: !MOVABLE.has(item.type) || item.status === 'trashed',
                    onClick: () => setMoving('copy'),
                  },
                  { label: 'View the change log', onClick: () => navigate(`/activity?item=${id}`) },
                  { label: 'View the activity', onClick: () => navigate(`/activity?project=${item.board_id}`) },
                  {
                    label: quietHere ? 'Notify me about this again' : "Don't notify me about this",
                    onClick: () =>
                      void setMuted({ item_id: id }, !quietHere).then((r) => {
                        setQuietHere(r.muted);
                        setNote(
                          r.muted ? "It won't show in Notifications any more." : 'It will show in Notifications again.',
                        );
                      }),
                  },
                  {
                    label: 'Remind me tomorrow',
                    onClick: () =>
                      void bubbleUp({ item_id: id }, 'tomorrow').then(() =>
                        setNote('It will come back tomorrow morning, in Notifications.'),
                      ),
                  },
                  {
                    label: 'Remind me next week',
                    onClick: () =>
                      void bubbleUp({ item_id: id }, 'next_week').then(() =>
                        setNote('It will come back next Monday morning, in Notifications.'),
                      ),
                  },
                  'sep',
                  {
                    label: 'Archive',
                    hidden: item.status !== 'active',
                    onClick: () =>
                      void setStatus('archived', 'Archived. It is out of the way, and Restore brings it back.'),
                  },
                  {
                    label: 'Put in the trash',
                    danger: true,
                    hidden: item.status === 'trashed' || item.status === 'drafted',
                    onClick: () =>
                      void setStatus('trashed', 'In the trash. Nothing is ever deleted: Restore brings it back.'),
                  },
                  {
                    label: 'Restore',
                    hidden: item.status !== 'archived' && item.status !== 'trashed',
                    onClick: () => void setStatus('active', ''),
                  },
                ]}
              />
            </>
          }
        />
        {note && (
          <p role="status" className="mb-4 rounded-lg bg-bc-today px-4 py-2 text-[15px]">
            {note}
          </p>
        )}
        {moving && (
          <MoveCopyDialog
            item={item}
            mode={moving}
            onCancel={() => setMoving(null)}
            onDone={(made) => {
              setMoving(null);
              if (moving === 'copy') {
                setNote('Copied. This is the copy.');
                navigate(`/i/${made.id}`);
              } else {
                setNote(`Moved to ${made.board_name}.`);
                load();
              }
            }}
          />
        )}
        {item.status === 'drafted' && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg bg-bc-today px-4 py-3">
            <span>
              {item.post_at ? <>Scheduled: it posts itself {on(item.post_at)}. </> : 'This is a draft. '}
              Nobody else sees it until it's posted.
              {item.post_at && (
                <button
                  type="button"
                  className="ml-2 text-bc-blue underline"
                  onClick={() => void quick({ post_at: null })}
                >
                  Don't schedule it
                </button>
              )}
            </span>
            <button
              type="button"
              className="bc-btn bc-btn-primary bc-btn-sm ml-auto"
              onClick={() => void setStatus('active', 'Posted.')}
            >
              Post this message
            </button>
          </div>
        )}
        {(item.status === 'archived' || item.status === 'trashed') && (
          <p className="mb-4 rounded-lg bg-bc-wash px-4 py-2 text-[15px]">
            This {LABEL[item.type]} is {item.status === 'trashed' ? 'in the trash' : 'archived'}.{' '}
            <button type="button" className="text-bc-blue underline" onClick={() => void setStatus('active', '')}>
              Restore it
            </button>
          </p>
        )}

        <article className="mx-auto max-w-3xl">
          {editing ? (
            <EditForm item={item} onSave={save} onCancel={() => setEditing(false)} />
          ) : (
            <>
              <header>
                {item.type === 'todo' ? (
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      className="bc-checkbox mt-3 scale-125"
                      checked={item.completed}
                      aria-label="Completed"
                      onChange={() => void completeItem(id, !item.completed).then(load)}
                    />
                    <h1
                      className={`bc-title text-[26px] sm:text-[30px] ${item.completed ? 'text-bc-subtle line-through' : ''}`}
                    >
                      {item.title}
                    </h1>
                  </div>
                ) : (
                  <h1 className="bc-title flex items-center gap-3 text-[26px] sm:text-[30px]">
                    {isList && (
                      <span className={`bc-c-${item.color}`}>
                        <ProgressPie
                          done={item.completed_count ?? 0}
                          total={item.todos_count ?? 0}
                          size={30}
                          color={item.color ? 'var(--c)' : undefined}
                        />
                      </span>
                    )}
                    {item.pinned_at && <span title="Pinned">📌</span>}
                    {item.type === 'link' && <span aria-hidden>🔗</span>}
                    {item.type === 'schedule_entry' && item.highlighted && (
                      <span title="Circled" aria-hidden>
                        ⭕
                      </span>
                    )}
                    {item.title || (item.type === 'answer' ? `${item.creator?.name ?? 'Someone'}'s answer` : '')}
                  </h1>
                )}
                <p className="mt-2 text-[16px] text-bc-subtle">
                  {CENTRED.has(item.type) ? '' : 'Added by '}
                  {item.creator?.name ?? 'Someone'} {on(item.created_at)}
                  {item.type === 'answer' && item.group_on && <> • for {day(item.group_on)}</>}
                  {item.category && <> • {item.category}</>}
                  {isList && (
                    <>
                      {' '}
                      • {item.completed_count}/{item.todos_count} completed
                    </>
                  )}
                  {item.completed && item.completer && (
                    <>
                      {' '}
                      • Completed by {item.completer.name} {item.completed_at && on(item.completed_at)}
                    </>
                  )}
                </p>
              </header>

              {CENTRED.has(item.type) && item.body && (
                <div className="mt-6 flex gap-3">
                  <span className="hidden sm:block">
                    <Avatar person={item.creator} size={40} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <Body text={item.body} />
                  </div>
                </div>
              )}

              {(item.type === 'link' || item.type === 'door') && (
                <div className="mt-6 text-center">
                  <a href={item.url} target="_blank" rel="noopener noreferrer" className="bc-btn bc-btn-primary">
                    Open the link ↗
                  </a>
                  <p className="mt-2 break-all text-[14px] text-bc-subtle">{item.url}</p>
                  {item.body && (
                    <div className="mt-4 text-left">
                      <Body text={item.body} />
                    </div>
                  )}
                </div>
              )}

              {item.type === 'schedule_entry' && (
                <div className="mt-4">
                  <EventFields item={item} save={(f) => void quick(f)} />
                  <Field label="Notes">
                    {item.body ? (
                      <Body text={item.body} />
                    ) : (
                      <button type="button" className="text-[15px] text-bc-faint" onClick={() => setEditing(true)}>
                        Add notes…
                      </button>
                    )}
                  </Field>
                </div>
              )}

              {item.type === 'question' && <QuestionView item={item} save={(f) => void quick(f)} reload={load} />}

              {item.type === 'todo' && (
                <div className="mt-4">
                  <Field label="Assigned to">
                    <PeoplePicker value={item.assignees} onChange={(ids) => void assign(ids)} />
                  </Field>
                  <Field label="Due on">
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="date"
                        value={item.starts_on ?? ''}
                        aria-label="Starts on"
                        className="bc-input w-auto py-1"
                        onChange={(e) =>
                          void updateItem(id, { starts_on: e.target.value || null })
                            .then(load)
                            .catch((err) => setNote(apiErrorMessage(err, 'Could not save the date.')))
                        }
                      />
                      <span className="text-bc-subtle">to</span>
                      <input
                        type="date"
                        value={item.due_on ?? ''}
                        aria-label="Due on"
                        className="bc-input w-auto py-1"
                        onChange={(e) =>
                          void updateItem(id, { due_on: e.target.value || null })
                            .then(load)
                            .catch((err) => setNote(apiErrorMessage(err, 'Could not save the date.')))
                        }
                      />
                    </div>
                  </Field>
                  <Field label="Repeats">
                    <select
                      value={item.repeat ?? ''}
                      aria-label="Repeat"
                      className="bc-input w-auto py-1"
                      onChange={(e) => void quick({ repeat: e.target.value || null })}
                    >
                      {REPEATS.map(([v, l]) => (
                        <option key={v} value={v}>
                          {l}
                        </option>
                      ))}
                    </select>
                    {item.repeat && (
                      <span className="ml-2 text-[14px] text-bc-subtle">Finishing it adds the next one.</span>
                    )}
                  </Field>
                  <Field label="Notes">
                    {item.body ? (
                      <Body text={item.body} />
                    ) : (
                      <button type="button" className="text-[15px] text-bc-faint" onClick={() => setEditing(true)}>
                        Add extra details or attach a link…
                      </button>
                    )}
                  </Field>
                  <Field label="Subtasks">
                    <Subtasks todo={item} steps={kids} reload={load} />
                  </Field>
                </div>
              )}

              {isList && (
                <div className={`bc-c-${item.color} mt-4`}>
                  {item.body && (
                    <div className="mb-3">
                      <Body text={item.body} />
                    </div>
                  )}
                  <ul>
                    {kids
                      .filter((k) => k.type === 'todo')
                      .map((t) => (
                        <TodoRow
                          key={t.id}
                          todo={t}
                          onChange={load}
                          onDropBefore={(d) => void dropTodo(d, id, t.id, load)}
                        />
                      ))}
                  </ul>
                  {kids
                    .filter((k) => k.type === 'todolist_group')
                    .map((g) => (
                      <div key={g.id} className={`bc-c-${g.color} mt-3`}>
                        <h3
                          className="border-b-2 pb-0.5 font-bold"
                          style={{ borderColor: g.color ? 'var(--c)' : 'var(--color-bc-line)' }}
                        >
                          <Link to={`/i/${g.id}`} className="hover:underline">
                            {g.title}
                          </Link>
                        </h3>
                        <ul className="mt-1">
                          {(g.todos ?? []).map((t) => (
                            <TodoRow
                              key={t.id}
                              todo={t}
                              onChange={load}
                              onDropBefore={(d) => void dropTodo(d, g.id, t.id, load)}
                            />
                          ))}
                        </ul>
                        {(g.completed_todos?.length ?? 0) > 0 && (
                          <CompletedToggle todos={g.completed_todos!} reload={load} />
                        )}
                      </div>
                    ))}
                  <AddTodo projectId={item.board_id} parentId={id} onAdded={load} />
                  {item.type === 'todolist' && <AddGroup list={item} onAdded={load} />}
                  {(thread.completed?.length ?? 0) > 0 && (
                    <div className="mt-4">
                      <h3 className="text-[15px] font-bold text-bc-green">✓ Completed</h3>
                      <ul>
                        {thread.completed!.map((t) => (
                          <TodoRow key={t.id} todo={t} onChange={load} />
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {item.type !== 'todolist_group' && (
                <div className="mt-6">
                  <Boosts
                    boosts={item.boosts ?? []}
                    onBoost={(c) => boostItem(id, c).then(load)}
                    onRemove={(b) => removeBoost(b).then(load)}
                  />
                </div>
              )}
            </>
          )}

          {item.type !== 'todolist_group' && item.type !== 'question' && (
            <Comments
              comments={thread.comments}
              me={me}
              onAdd={(t) =>
                commentOn(id, t).then(() => {
                  reloadPeople();
                  load();
                })
              }
              onBoost={(cid, c) => boostItem(cid, c).then(load)}
              onRemoveBoost={(b) => removeBoost(b).then(load)}
            />
          )}
        </article>
      </Perma>
    </ProjectsShell>
  );
}

function AddGroup({ list, onAdded }: { list: Item; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  if (!open)
    return (
      <button type="button" className="ml-4 mt-1 text-[15px] text-bc-blue underline" onClick={() => setOpen(true)}>
        Add a group
      </button>
    );
  return (
    <form
      className="mt-2 flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim())
          void createItem(list.board_id, 'todolist_group', { title: title.trim() }, { parent_id: list.id }).then(() => {
            setTitle('');
            setOpen(false);
            onAdded();
          });
      }}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        placeholder="Name this group…"
        aria-label="Group name"
        maxLength={500}
        className="bc-input py-1"
      />
      <button type="submit" className="bc-btn bc-btn-sm" disabled={!title.trim()}>
        Add group
      </button>
      <button type="button" className="bc-btn bc-btn-sm" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </form>
  );
}
