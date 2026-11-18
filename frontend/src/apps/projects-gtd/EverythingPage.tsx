// Projects GTD — Everything (key 4), search, and a project's archive and trash.
// Everything lists one kind across every project, newest first (messages, docs
// & files, tasks with subtasks on request, comments, check-in answers). Search
// finds words in every project, archived things too, narrowed by kind, project,
// person and date. The archive page lists what a project has put away; Restore
// brings each back where it was (the trash never empties).
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import {
  getEverything,
  getProject,
  getPutAway,
  listBoards,
  search,
  updateCard,
  updateItem,
  type EverythingKind,
  type PutAway,
  type ReportItem,
  type SearchResult,
} from './api';
import { ProjectsShell, usePeople } from './ProjectsShell';
import type { BoardSummary, Item, Project } from './types';
import { Avatar, Crumbs, EmptyState, Perma, plain, when } from './ui';

const KINDS: [EverythingKind, string][] = [
  ['messages', 'Messages'],
  ['docs', 'Docs'],
  ['tasks', 'Tasks'],
  ['comments', 'Comments'],
  ['checkins', 'Check-ins'],
];
const TYPE_LABEL: Record<string, string> = {
  message: 'Message',
  document: 'Document',
  link: 'Link',
  vault: 'Folder',
  todolist: 'To-do list',
  todo: 'To-do',
  comment: 'Comment',
  schedule_entry: 'Event',
  question: 'Check-in',
  answer: 'Answer',
  card: 'Card',
  step: 'Subtask',
  todolist_group: 'Group',
};

/** Where a thing opens: a card on its table, anything else on its page. */
function path(i: {
  type: string;
  id: number;
  board_id: number;
  card_id?: number | null;
  parent_id?: number | null;
}): string {
  if (i.type === 'card') return `/p/${i.board_id}/cards?card=${i.id}`;
  if (i.type === 'comment')
    return i.card_id ? `/p/${i.board_id}/cards?card=${i.card_id}` : `/i/${i.parent_id}#comment-${i.id}`;
  if (i.type === 'step') return i.card_id ? `/p/${i.board_id}/cards?card=${i.card_id}` : `/i/${i.parent_id}`;
  return `/i/${i.id}`;
}

function Row({ item }: { item: ReportItem }) {
  const text =
    item.type === 'comment' || item.type === 'answer'
      ? plain(item.body ?? '')
      : item.type === 'card'
        ? (item.column_name ?? '')
        : plain(item.body ?? '');
  const heading =
    item.type === 'comment'
      ? `Re: ${item.on_title ?? ''}`
      : item.type === 'answer'
        ? (item.on_title ?? 'Answer')
        : item.title;
  return (
    <li className="flex gap-3 border-b border-bc-line py-3">
      <Avatar person={item.creator} size={32} />
      <Link to={path(item)} className="min-w-0 flex-1 hover:underline">
        <span className="block truncate font-semibold">{heading}</span>
        {text && <span className="line-clamp-2 block text-[14px] text-bc-subtle">{text}</span>}
        <span className="block text-[13px] text-bc-faint">
          {TYPE_LABEL[item.type] ?? item.type} · {item.board_name} ·{' '}
          {item.creator?.name ? `${item.creator.name} · ` : ''}
          {when(item.created_at)}
        </span>
      </Link>
    </li>
  );
}

export function EverythingPage() {
  const [params, setParams] = useSearchParams();
  const kind = (params.get('kind') as EverythingKind) || 'messages';
  const [subtasks, setSubtasks] = useState(false);
  const [items, setItems] = useState<ReportItem[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    getEverything(kind, null, subtasks).then(
      (r) => {
        setItems(r.items);
        setNext(r.next_before);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load this.')),
    );
  }, [kind, subtasks]);
  const more = () => {
    if (next)
      void getEverything(kind, next, subtasks).then((r) => {
        setItems((i) => [...i, ...r.items]);
        setNext(r.next_before);
      });
  };
  return (
    <ProjectsShell title="Everything">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Everything' }]} />
        <h1 className="bc-title text-2xl">Everything</h1>
        <div role="tablist" className="mt-4 flex flex-wrap justify-center gap-2">
          {KINDS.map(([k, label]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={kind === k}
              onClick={() => setParams({ kind: k })}
              className={`rounded-full border px-3 py-1 text-[15px] ${kind === k ? 'border-bc-ink bg-bc-ink font-bold text-bc-canvas' : 'border-bc-line'}`}
            >
              {label}
            </button>
          ))}
        </div>
        {kind === 'tasks' && (
          <label className="mt-3 flex items-center justify-center gap-1.5 text-[14px]">
            <input
              type="checkbox"
              className="bc-checkbox"
              checked={subtasks}
              onChange={(e) => setSubtasks(e.target.checked)}
            />{' '}
            Show subtasks
          </label>
        )}
        {error && (
          <p role="alert" className="mt-3 text-bc-unread">
            {error}
          </p>
        )}
        {!items.length && !error && (
          <div className="mt-6">
            <EmptyState title="Nothing here yet." />
          </div>
        )}
        <ul className="mx-auto mt-4 max-w-3xl">
          {items.map((i) => (
            <Row key={`${i.type}${i.id}`} item={i} />
          ))}
        </ul>
        {next && (
          <p className="mt-4 text-center">
            <button type="button" className="bc-btn" onClick={more}>
              Show more
            </button>
          </p>
        )}
      </Perma>
    </ProjectsShell>
  );
}

const SEARCH_KINDS = [
  'message',
  'document',
  'link',
  'vault',
  'todolist',
  'todo',
  'comment',
  'schedule_entry',
  'question',
  'answer',
  'card',
];

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const { people } = usePeople();
  const [projects, setProjects] = useState<BoardSummary[]>([]);
  const [q, setQ] = useState(params.get('q') ?? '');
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    listBoards().then(setProjects, () => {});
  }, []);
  const asked = params.toString();
  const [previousAsked, setPreviousAsked] = useState(asked);
  if (asked !== previousAsked) {
    setPreviousAsked(asked);
    if (!params.get('q')?.trim()) setResults(null);
  }
  useEffect(() => {
    const p = Object.fromEntries(new URLSearchParams(asked));
    if (!p.q?.trim()) return;
    search(p).then(
      (r) => {
        setResults(r.results);
        setCount(r.count);
        setError('');
      },
      (e) => setError(apiErrorMessage(e, 'Could not search.')),
    );
  }, [asked]);
  const pick = (key: string, value: string) => {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p, { replace: true });
  };
  return (
    <ProjectsShell title={params.get('q') ? `“${params.get('q')}” · Search` : 'Search'}>
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Search' }]} />
        <form
          className="mx-auto max-w-3xl"
          onSubmit={(e) => {
            e.preventDefault();
            pick('q', q.trim());
          }}
        >
          <div className="flex gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              autoFocus
              maxLength={200}
              aria-label="Search for"
              placeholder="Search every project…"
              className="bc-input text-[18px]"
            />
            <button type="submit" className="bc-btn bc-btn-primary">
              Search
            </button>
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-[14px]">
            <select
              value={params.get('kind') ?? ''}
              onChange={(e) => pick('kind', e.target.value)}
              aria-label="Kind"
              className="bc-input w-auto py-1"
            >
              <option value="">Everything</option>
              {SEARCH_KINDS.map((k) => (
                <option key={k} value={k}>
                  {TYPE_LABEL[k]}s
                </option>
              ))}
            </select>
            <select
              value={params.get('project_id') ?? ''}
              onChange={(e) => pick('project_id', e.target.value)}
              aria-label="Project"
              className="bc-input w-auto py-1"
            >
              <option value="">In any project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              value={params.get('person_id') ?? ''}
              onChange={(e) => pick('person_id', e.target.value)}
              aria-label="By"
              className="bc-input w-auto py-1"
            >
              <option value="">By anyone</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={params.get('since') ?? ''}
              onChange={(e) => pick('since', e.target.value)}
              aria-label="Since"
              className="bc-input w-auto py-1"
            />
            <select
              value={params.get('sort') ?? 'best'}
              onChange={(e) => pick('sort', e.target.value === 'best' ? '' : e.target.value)}
              aria-label="Sort"
              className="bc-input w-auto py-1"
            >
              <option value="best">Best match</option>
              <option value="recent">Most recent</option>
            </select>
          </div>
        </form>
        {error && (
          <p role="alert" className="mt-3 text-center text-bc-unread">
            {error}
          </p>
        )}
        {results && (
          <p className="mx-auto mt-4 max-w-3xl text-[14px] text-bc-subtle">
            {count === 0
              ? 'Nothing found.'
              : `${count} found${count > results.length ? `; the first ${results.length} shown` : ''}.`}
          </p>
        )}
        <ul className="mx-auto max-w-3xl">
          {results?.map((r) => (
            <li key={`${r.type}${r.id}`} className="border-b border-bc-line py-3">
              <Link to={path(r)} className="block hover:underline">
                <span className="block font-semibold">
                  {r.title || (r.type === 'comment' ? 'A comment' : TYPE_LABEL[r.type])}
                </span>
                {r.snippet && <span className="block text-[14px] text-bc-subtle">{plain(r.snippet)}</span>}
                <span className="block text-[13px] text-bc-faint">
                  {TYPE_LABEL[r.type] ?? r.type} · {r.board_name}
                  {r.status === 'archived' ? ' · archived' : ''} · {when(r.created_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Perma>
    </ProjectsShell>
  );
}

export function ArchivePage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [away, setAway] = useState<PutAway | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    getPutAway(id).then(setAway, (e) => setError(apiErrorMessage(e, 'Could not load the archive.')));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    getProject(id).then(setProject, () => {});
  }, [id]);
  const restore = (item: Item) =>
    void updateItem(item.id, { status: 'active' }).then(load, (e) =>
      setError(apiErrorMessage(e, 'Could not restore it.')),
    );
  const list = (items: Item[]) => (
    <ul>
      {items.map((i) => (
        <li key={i.id} className="flex items-center gap-3 border-b border-bc-line py-2.5">
          <Link to={path(i)} className="min-w-0 flex-1 hover:underline">
            <span className="block truncate font-semibold">
              {i.title || plain(i.body).slice(0, 80) || TYPE_LABEL[i.type]}
            </span>
            <span className="block text-[13px] text-bc-subtle">
              {TYPE_LABEL[i.type] ?? i.type} · {when(i.updated_at)}
            </span>
          </Link>
          <button type="button" className="bc-btn bc-btn-sm" onClick={() => restore(i)}>
            Restore
          </button>
        </li>
      ))}
    </ul>
  );
  return (
    <ProjectsShell project={project} title={`Archive · ${project?.name ?? ''}`}>
      <Perma>
        <Crumbs
          project={project}
          crumbs={[{ label: project?.name ?? '…', to: `/p/${id}` }, { label: 'Archived and trashed' }]}
        />
        <h1 className="bc-title text-2xl">Archived and trashed</h1>
        <p className="text-center text-bc-subtle">
          Nothing here is ever deleted. Restore puts each thing back where it was.
        </p>
        {error && (
          <p role="alert" className="mt-3 text-bc-unread">
            {error}
          </p>
        )}
        {away && !away.archived.length && !away.trashed.length && !away.cards.length && (
          <div className="mt-6">
            <EmptyState title="Nothing archived or in the trash." />
          </div>
        )}
        {away && away.archived.length > 0 && (
          <section className="mt-6">
            <h2 className="font-bold">Archived</h2>
            {list(away.archived)}
          </section>
        )}
        {away && away.cards.length > 0 && (
          <section className="mt-6">
            <h2 className="font-bold">Archived cards</h2>
            <ul>
              {away.cards.map((c) => (
                <li key={c.id} className="flex items-center gap-3 border-b border-bc-line py-2.5">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold">▤ {c.title}</span>
                    <span className="block text-[13px] text-bc-subtle">
                      {c.column_name} · {when(c.updated_at)}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="bc-btn bc-btn-sm"
                    onClick={() =>
                      void updateCard(c.id, { status: 'active' }).then(load, (e) =>
                        setError(apiErrorMessage(e, 'Could not restore it.')),
                      )
                    }
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        {away && away.trashed.length > 0 && (
          <section className="mt-6">
            <h2 className="font-bold">In the trash</h2>
            {list(away.trashed)}
          </section>
        )}
      </Perma>
    </ProjectsShell>
  );
}
