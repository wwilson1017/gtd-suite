// Projects GTD — the pages My Bar opens: Activity (everything, or one project or
// one person: you, an AI tool), My Tasks (open to-dos assigned to someone, soonest
// first), My Bookmarks, and People (the account's people, add someone by name).
import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import {
  addPerson,
  getActivity,
  getAssignments,
  getDrafts,
  getMyBoosts,
  getUpNext,
  listBoards,
  listBookmarks,
  setBookmark,
  setUpNext,
  updatePerson,
  type Mention,
  type MyBoost,
  type UpNextItem,
} from './api';
import { ActivityLine } from './HomePage';
import { ProjectsShell, usePeople } from './ProjectsShell';
import { TodoRow } from './TodosPage';
import { todayStr } from '../todo-gtd/util';
import type { ActivityEvent, BoardSummary, Bookmark, Card, Item, Person } from './types';
import { Avatar, Crumbs, day, dueTone, EmptyState, itemPath, on, Perma, when } from './ui';

/** Events grouped under the day they happened on. */
function byDay(events: ActivityEvent[]): [string, ActivityEvent[]][] {
  const out: [string, ActivityEvent[]][] = [];
  for (const e of events) {
    const label = new Date(e.created_at).toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
    });
    if (out.length && out[out.length - 1][0] === label) out[out.length - 1][1].push(e);
    else out.push([label, [e]]);
  }
  return out;
}

export function ActivityPage() {
  const [params, setParams] = useSearchParams();
  const project = params.get('project') ? Number(params.get('project')) : undefined;
  const item = params.get('item') ? Number(params.get('item')) : undefined; // one item's change log
  const { people, me } = usePeople();
  // ?person=me is My Activity (Shift+Y); before I have done anything there is none.
  const mine = params.get('person') === 'me';
  const person = mine ? me?.id : params.get('person') ? Number(params.get('person')) : undefined;
  const [projects, setProjects] = useState<BoardSummary[]>([]);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    listBoards().then(setProjects, () => {});
  }, []);
  const [previousFilter, setPreviousFilter] = useState({ project, person, item, mine });
  if (
    project !== previousFilter.project ||
    person !== previousFilter.person ||
    item !== previousFilter.item ||
    mine !== previousFilter.mine
  ) {
    setPreviousFilter({ project, person, item, mine });
    if (mine && person === undefined) {
      setEvents([]);
      setNext(null);
    }
  }
  useEffect(() => {
    if (mine && person === undefined) return;
    getActivity({ project_id: project, person_id: person, item_id: item }).then(
      (r) => {
        setEvents(r.events);
        setNext(r.next_before);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load the activity.')),
    );
  }, [project, person, item, mine]);
  const more = () => {
    if (next === null) return;
    void getActivity({ project_id: project, person_id: person, item_id: item, before: next }).then((r) => {
      setEvents((ev) => [...ev, ...r.events]);
      setNext(r.next_before);
    });
  };
  const pick = (key: string, value: string) => {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p, { replace: true });
  };
  return (
    <ProjectsShell title="Activity">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Activity' }]} />
        <h1 className="bc-title text-2xl">{item ? 'Change log' : 'Latest activity'}</h1>
        {item && (
          <p className="text-center">
            <Link to={`/i/${item}`} className="text-bc-blue underline">
              Back to the item
            </Link>
          </p>
        )}
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <select
            value={project ?? ''}
            onChange={(e) => pick('project', e.target.value)}
            aria-label="Project"
            className="bc-input w-auto"
          >
            <option value="">Everything</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={person ?? ''}
            onChange={(e) => pick('person', e.target.value)}
            aria-label="Person"
            className="bc-input w-auto"
          >
            <option value="">By anyone</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.kind === 'ai' ? ' (AI)' : ''}
              </option>
            ))}
          </select>
        </div>
        {error && (
          <p role="alert" className="mt-3 text-bc-unread">
            {error}
          </p>
        )}
        <div className="mx-auto mt-6 max-w-2xl">
          {events.length === 0 && !error && <EmptyState title="Nothing has happened here yet." />}
          {byDay(events).map(([label, list]) => (
            <section key={label} className="mb-6">
              <h2 className="sticky top-0 bg-bc-canvas py-1 text-[13px] font-bold uppercase tracking-wider text-bc-subtle">
                {label}
              </h2>
              <ol className="mt-2 space-y-4 border-l border-bc-line pl-4">
                {list.map((e) => (
                  <li key={e.id}>
                    <ActivityLine e={e} showProject={!project} />
                  </li>
                ))}
              </ol>
            </section>
          ))}
          {next !== null && (
            <button type="button" className="bc-btn" onClick={more}>
              Show more
            </button>
          )}
        </div>
      </Perma>
    </ProjectsShell>
  );
}

type TaskTab = 'mine' | 'dates' | 'others';

/** One open to-do or card on My Tasks, with the ↑ that puts it in Up Next. */
function TaskLine({
  item,
  kind,
  today,
  onUp,
  reload,
}: {
  item: Item | Card;
  kind: 'r' | 'c';
  today: string;
  onUp?: () => void;
  reload: () => void;
}) {
  const due = kind === 'r' ? (item as Item).due_on : (item as Card).due_date;
  return (
    <li className="flex items-center gap-2">
      <div className="min-w-0 flex-1">
        {kind === 'r' ? (
          <ul>
            <TodoRow todo={item as Item} onChange={reload} />
          </ul>
        ) : (
          <div className="flex items-center gap-2 py-1.5 text-[17px]">
            <span aria-hidden title="Card" className="text-bc-subtle">
              ▤
            </span>
            <Link to={`/p/${item.board_id}/cards?card=${item.id}`} className="truncate hover:underline">
              {item.title}
            </Link>
            <span className="text-[13px] text-bc-subtle">{(item as Card).column_name}</span>
            {due && (
              <span className={`rounded px-1.5 text-[12px] font-semibold ${dueTone(due, false, today)}`}>
                {day(due)}
              </span>
            )}
          </div>
        )}
      </div>
      {onUp && (
        <button
          type="button"
          title="Move to Up Next"
          aria-label={`Put ${item.title} in Up Next`}
          onClick={onUp}
          className="shrink-0 rounded-full border border-bc-line px-2 text-[14px] hover:bg-bc-wash"
        >
          ↑
        </button>
      )}
    </li>
  );
}

/** A mention leads to its chat, its card, or the item it is on. */
export const mentionPath = (m: Mention) =>
  itemPath(m.board_id, {
    recording_id: m.type === 'chat_line' ? null : m.type === 'comment' ? m.parent_id : m.id,
    card_id: m.card_id,
    action: m.type === 'chat_line' ? 'chatted' : undefined,
  });

export function MyTasksPage() {
  const { people } = usePeople();
  const [tab, setTab] = useState<TaskTab>('mine');
  const [mine, setMine] = useState<{ todos: Item[]; cards: Card[]; mentions?: Mention[] } | null>(null);
  const [others, setOthers] = useState<[Person, { todos: Item[]; cards: Card[] }][]>([]);
  const [upNext, setUpNextItems] = useState<UpNextItem[]>([]);
  const [tick, setTick] = useState(1);
  const today = todayStr();
  const load = useCallback(() => {
    getAssignments().then(setMine, () => setMine({ todos: [], cards: [] }));
    getUpNext().then(setUpNextItems, () => {});
  }, []);
  const refresh = () => {
    load();
    setTick((t) => t + 1);
  };
  useEffect(load, [load]);
  useEffect(() => {
    if (tab !== 'others' || !tick) return;
    const them = people.filter((p) => p.kind !== 'me');
    void Promise.all(
      them.map((p) => getAssignments(p.id).then((a) => [p, a] as [Person, { todos: Item[]; cards: Card[] }])),
    ).then((rows) => setOthers(rows.filter(([, a]) => a.todos.length + a.cards.length > 0)));
  }, [tab, people, tick]);

  const ref = (i: { kind?: string; id: number }, kind?: 'r' | 'c'): ['r' | 'c', number] => [
    kind ?? (i.kind === 'card' ? 'c' : 'r'),
    i.id,
  ];
  const saveUpNext = (next: ['r' | 'c', number][]) => void setUpNext(next).then(setUpNextItems);
  const current = upNext.map((i) => ref(i));
  const inUpNext = (kind: 'r' | 'c', id: number) => current.some(([k, i]) => k === kind && i === id);
  const nudge = (index: number, by: number) => {
    const next = [...current];
    const [moved] = next.splice(index, 1);
    next.splice(Math.max(0, Math.min(next.length, index + by)), 0, moved);
    saveUpNext(next);
  };
  const todos = (mine?.todos ?? []).filter((t) => !inUpNext('r', t.id));
  const cards = (mine?.cards ?? []).filter((c) => !inUpNext('c', c.id));
  const byProject = new Map<string, { id: number; todos: Item[]; cards: Card[] }>();
  const slot = (name: string, id: number) =>
    byProject.get(name) ?? byProject.set(name, { id, todos: [], cards: [] }).get(name)!;
  for (const t of todos) slot(t.board_name, t.board_id).todos.push(t);
  for (const c of cards) slot(c.board_name, c.board_id).cards.push(c);
  const dated = [
    ...todos.map((t) => ({ kind: 'r' as const, item: t as Item | Card, due: t.due_on })),
    ...cards.map((c) => ({ kind: 'c' as const, item: c as Item | Card, due: c.due_date })),
  ]
    .filter((x) => x.due)
    .sort((a, b) => (a.due! < b.due! ? -1 : 1));
  const tabCls = (t: TaskTab) =>
    `rounded-full px-3 py-1 text-[15px] ${tab === t ? 'bg-bc-ink text-bc-canvas' : 'text-bc-subtle hover:bg-bc-wash'}`;

  return (
    <ProjectsShell title="My Tasks">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'My Tasks' }]} />
        <h1 className="bc-title text-2xl">My Tasks</h1>
        <div className="mt-3 flex justify-center gap-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'mine'}
            className={tabCls('mine')}
            onClick={() => setTab('mine')}
          >
            My tasks
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'dates'}
            className={tabCls('dates')}
            onClick={() => setTab('dates')}
          >
            With dates
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'others'}
            className={tabCls('others')}
            onClick={() => setTab('others')}
          >
            Assigned to others
          </button>
        </div>
        <div className="mx-auto mt-6 max-w-2xl">
          {tab !== 'others' && upNext.length > 0 && (
            <section className="mb-8 rounded-lg bg-bc-wash p-3">
              <h2 className="text-[13px] font-bold uppercase tracking-wider text-bc-subtle">
                Up Next <span className="font-normal normal-case tracking-normal">— only you see this order</span>
              </h2>
              <ol className="mt-1">
                {upNext.map((i, n) => (
                  <li key={`${i.kind}${i.id}`} className="flex items-center gap-1">
                    <span className="w-5 text-right text-[13px] text-bc-faint">{n + 1}.</span>
                    <div className="min-w-0 flex-1">
                      <ul>
                        <TaskLine item={i} kind={i.kind === 'card' ? 'c' : 'r'} today={today} reload={refresh} />
                      </ul>
                    </div>
                    <button
                      type="button"
                      aria-label="Earlier"
                      disabled={n === 0}
                      onClick={() => nudge(n, -1)}
                      className="rounded px-1 text-bc-subtle disabled:opacity-30"
                    >
                      ▲
                    </button>
                    <button
                      type="button"
                      aria-label="Later"
                      disabled={n === upNext.length - 1}
                      onClick={() => nudge(n, 1)}
                      className="rounded px-1 text-bc-subtle disabled:opacity-30"
                    >
                      ▼
                    </button>
                    <button
                      type="button"
                      aria-label={`Take ${i.title} out of Up Next`}
                      onClick={() => saveUpNext(current.filter((_, k) => k !== n))}
                      className="rounded-full border border-bc-line px-2 text-[14px] hover:bg-bc-canvas"
                    >
                      ↓
                    </button>
                  </li>
                ))}
              </ol>
            </section>
          )}
          {tab === 'mine' && (
            <>
              {mine && todos.length + cards.length + upNext.length === 0 && (
                <EmptyState title="Nothing assigned.">
                  To-dos and cards assigned to you show up here. ↑ puts one in Up Next.
                </EmptyState>
              )}
              {(mine?.mentions?.length ?? 0) > 0 && (
                <section className="mb-8">
                  <h2 className="text-[13px] font-bold uppercase tracking-wider text-bc-subtle">
                    Where you were mentioned{' '}
                    <span className="font-normal normal-case tracking-normal">— the last two weeks</span>
                  </h2>
                  <ul className="mt-1">
                    {mine!.mentions!.map((m) => (
                      <li key={m.id} className="flex items-start gap-2 border-b border-bc-line py-2">
                        <Avatar person={m.creator} size={24} />
                        <Link to={mentionPath(m)} className="min-w-0 flex-1 hover:underline">
                          <span className="text-[13px] text-bc-subtle">
                            {m.creator?.name ?? 'Someone'} in {m.board_name} · {when(m.created_at)}
                          </span>
                          <span className="block truncate">{m.excerpt}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {[...byProject].map(([name, group]) => (
                <section key={name} className="mb-6">
                  <h2 className="text-[20px] font-bold">
                    <Link to={`/p/${group.id}`} className="hover:underline">
                      {name}
                    </Link>
                  </h2>
                  <ul className="mt-1">
                    {group.todos.map((t) => (
                      <TaskLine
                        key={`r${t.id}`}
                        item={t}
                        kind="r"
                        today={today}
                        reload={refresh}
                        onUp={() => saveUpNext([...current, ['r', t.id]])}
                      />
                    ))}
                    {group.cards.map((c) => (
                      <TaskLine
                        key={`c${c.id}`}
                        item={c}
                        kind="c"
                        today={today}
                        reload={refresh}
                        onUp={() => saveUpNext([...current, ['c', c.id]])}
                      />
                    ))}
                  </ul>
                </section>
              ))}
            </>
          )}
          {tab === 'dates' && (
            <ul>
              {dated.length === 0 && <li className="text-bc-subtle">Nothing of yours has a date.</li>}
              {dated.map((x) => (
                <TaskLine
                  key={`${x.kind}${x.item.id}`}
                  item={x.item}
                  kind={x.kind}
                  today={today}
                  reload={refresh}
                  onUp={() => saveUpNext([...current, [x.kind, x.item.id]])}
                />
              ))}
            </ul>
          )}
          {tab === 'others' && (
            <>
              {others.length === 0 && (
                <EmptyState title="Nothing assigned to anyone else.">
                  Assign to-dos and cards to your AI tools and the people you added; they show up here by person.
                </EmptyState>
              )}
              {others.map(([p, a]) => (
                <section key={p.id} className="mb-6">
                  <h2 className="flex items-center gap-2 text-[20px] font-bold">
                    <Avatar person={p} size={28} />
                    {p.name}
                    {p.kind === 'ai' && <span className="text-[14px] font-normal text-bc-subtle">AI tool</span>}
                  </h2>
                  <ul className="mt-1">
                    {a.todos.map((t) => (
                      <TaskLine key={`r${t.id}`} item={t} kind="r" today={today} reload={refresh} />
                    ))}
                    {a.cards.map((c) => (
                      <TaskLine key={`c${c.id}`} item={c} kind="c" today={today} reload={refresh} />
                    ))}
                  </ul>
                </section>
              ))}
            </>
          )}
        </div>
      </Perma>
    </ProjectsShell>
  );
}

export function DraftsPage() {
  const [drafts, setDrafts] = useState<Item[] | null>(null);
  useEffect(() => {
    getDrafts().then(setDrafts, () => setDrafts([]));
  }, []);
  return (
    <ProjectsShell title="My Drafts">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'My Drafts' }]} />
        <h1 className="bc-title text-2xl">My Drafts</h1>
        <p className="mx-auto mt-2 max-w-xl text-center text-bc-subtle">
          Messages not posted yet: yours, and the ones your AI tools wrote for you to look over and post.
        </p>
        <ul className="mx-auto mt-6 max-w-2xl">
          {drafts?.length === 0 && (
            <li>
              <EmptyState title="No drafts." />
            </li>
          )}
          {drafts?.map((d) => (
            <li key={d.id} className="flex gap-3 border-b border-bc-line py-3">
              <Avatar person={d.creator} size={36} />
              <div className="min-w-0">
                <Link to={`/i/${d.id}`} className="text-[17px] font-bold hover:underline">
                  {d.title}
                </Link>
                <p className="text-[14px] text-bc-subtle">
                  {d.creator?.name} · {d.board_name} ·{' '}
                  {d.post_at ? `🕓 posts itself ${on(d.post_at)}` : when(d.updated_at)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Perma>
    </ProjectsShell>
  );
}

export function BoostsPage() {
  const [boosts, setBoosts] = useState<MyBoost[] | null>(null);
  useEffect(() => {
    getMyBoosts().then(setBoosts, () => setBoosts([]));
  }, []);
  return (
    <ProjectsShell title="My Reactions">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'My Reactions' }]} />
        <h1 className="bc-title text-2xl">My Reactions</h1>
        <ul className="mx-auto mt-6 max-w-2xl">
          {boosts?.length === 0 && (
            <li>
              <EmptyState title="No reactions yet.">
                When someone reacts to something you wrote, it shows up here.
              </EmptyState>
            </li>
          )}
          {boosts?.map((b) => (
            <li key={b.id} className="flex items-center gap-3 border-b border-bc-line py-3">
              <span className="bc-boost">
                <Avatar person={b.booster} size={26} />
                <span>{b.content}</span>
              </span>
              <span className="min-w-0 text-[15px]">
                <span className="font-bold">{b.booster?.name}</span> reacted to{' '}
                <Link to={itemPath(b.board_id, b)} className="text-bc-blue underline">
                  {b.title}
                </Link>
                <span className="block text-[13px] text-bc-faint">{when(b.created_at)}</span>
              </span>
            </li>
          ))}
        </ul>
      </Perma>
    </ProjectsShell>
  );
}

const KIND: Record<string, string> = {
  message: 'Message',
  todolist: 'To-do list',
  todolist_group: 'Group',
  todo: 'To-do',
  step: 'Subtask',
  comment: 'Comment',
};

export function BookmarksPage() {
  const [marks, setMarks] = useState<Bookmark[] | null>(null);
  const load = useCallback(() => {
    listBookmarks().then(setMarks, () => setMarks([]));
  }, []);
  useEffect(load, [load]);
  return (
    <ProjectsShell title="My Bookmarks">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'My Bookmarks' }]} />
        <h1 className="bc-title text-2xl">My Bookmarks</h1>
        <div className="mx-auto mt-6 max-w-2xl">
          {marks && marks.length === 0 && (
            <EmptyState title="No bookmarks yet.">
              Click 🔖 Bookmark at the top of any project or item to keep it here.
            </EmptyState>
          )}
          <ul>
            {marks?.map((b) => (
              <li key={b.id} className="flex items-center gap-3 border-b border-bc-line py-3">
                <div className="min-w-0 flex-1">
                  <Link
                    to={b.board_id ? `/p/${b.board_id}` : itemPath(b.project_id, b)}
                    className="text-[17px] font-bold hover:underline"
                  >
                    {b.title}
                  </Link>
                  <p className="text-[14px] text-bc-subtle">
                    {b.board_id ? 'Project' : b.card_id ? 'Card' : (KIND[b.recording_type ?? ''] ?? 'Item')}
                    {!b.board_id && <> in {b.board_name}</>}
                  </p>
                </div>
                <button
                  type="button"
                  className="text-[14px] text-bc-subtle underline"
                  onClick={() =>
                    void setBookmark(
                      b.board_id
                        ? { project_id: b.board_id }
                        : b.card_id
                          ? { card_id: b.card_id }
                          : { item_id: b.recording_id! },
                      false,
                    ).then(load)
                  }
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      </Perma>
    </ProjectsShell>
  );
}

const KIND_LABEL: Record<Person['kind'], string> = { me: 'You', person: 'Added by name', ai: 'AI tool' };

export function PeoplePage() {
  const { people, reload } = usePeople();
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const add = async () => {
    try {
      await addPerson(name.trim(), title.trim());
      setName('');
      setTitle('');
      setError('');
      reload();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not add them.'));
    }
  };
  const rename = async (p: Person) => {
    const next = prompt(`Rename ${p.name}`, p.name);
    if (next && next.trim() && next.trim() !== p.name) {
      await updatePerson(p.id, { name: next.trim() }).catch((e) => setError(apiErrorMessage(e, 'Could not rename.')));
      reload();
    }
  };
  return (
    <ProjectsShell title="People">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'People' }]} />
        <h1 className="bc-title text-2xl">People</h1>
        <p className="mx-auto mt-2 max-w-xl text-center text-bc-subtle">
          You, the people you work with, and your AI tools. Your AI tools appear here the first time they write
          something. Anyone can be assigned to-dos; people added by name don't sign in.
        </p>
        <form
          className="mx-auto mt-6 flex max-w-xl flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void add();
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name"
            aria-label="Name"
            maxLength={200}
            className="bc-input min-w-40 flex-1"
          />
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (optional)"
            aria-label="Title"
            maxLength={200}
            className="bc-input min-w-40 flex-1"
          />
          <button type="submit" className="bc-btn bc-btn-primary" disabled={!name.trim()}>
            Add person
          </button>
        </form>
        {error && (
          <p role="alert" className="mt-2 text-center text-bc-unread">
            {error}
          </p>
        )}
        <ul className="mx-auto mt-6 grid max-w-3xl gap-3 sm:grid-cols-2">
          {people.map((p) => (
            <li key={p.id} className="flex items-center gap-3 rounded-lg border border-bc-line p-3">
              <Avatar person={p} size={44} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[17px] font-bold">{p.name}</p>
                <p className="truncate text-[14px] text-bc-subtle">{p.title || KIND_LABEL[p.kind]}</p>
                <p className="mt-0.5 flex gap-3 text-[13px]">
                  <Link to={`/activity?person=${p.id}`} className="text-bc-blue underline">
                    Activity
                  </Link>
                  <button type="button" className="text-bc-blue underline" onClick={() => void rename(p)}>
                    Rename
                  </button>
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Perma>
    </ProjectsShell>
  );
}
