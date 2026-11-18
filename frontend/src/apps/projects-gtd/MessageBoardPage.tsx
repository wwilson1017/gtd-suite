// Projects GTD — the Message Board: pinned posts first, then the rest by the sort
// chosen (newest, latest comment, A–Z), a category filter, drafts; and the form
// that writes a new message (subject, category, body; post it or save a draft).
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { createItem, getProject, listItems } from './api';
import { ProjectsShell } from './ProjectsShell';
import type { Item, Project } from './types';
import { Avatar, Crumbs, EmptyState, MentionPicker, Menu, Perma, plain, when } from './ui';

export const CATEGORIES = ['📢 Announcement', '✨ FYI', '❤️ Heartbeat', '💡 Pitch', '❓ Question'];

function toolTitle(project: Project | null, tool: string, fallback: string): string {
  return project?.dock.find((t) => t.tool === tool)?.title ?? fallback;
}

function Row({ m }: { m: Item }) {
  return (
    <li className="border-b border-bc-line">
      <Link to={`/i/${m.id}`} className="flex gap-3 py-4 hover:bg-bc-wash sm:px-2">
        <Avatar person={m.creator} size={40} />
        <div className="min-w-0 flex-1">
          <p className="text-[18px] font-bold leading-snug">
            {m.pinned_at && (
              <span title="Pinned" className="mr-1">
                📌
              </span>
            )}
            {m.category && (
              <span className="mr-1" title={m.category}>
                {m.category.split(' ')[0]}
              </span>
            )}
            {m.title}
          </p>
          <p className="line-clamp-2 text-[15px] text-bc-subtle">
            <span className="text-bc-ink">{m.creator?.name ?? 'Someone'}</span> • {when(m.created_at)}
            {m.body && <> — {plain(m.body).slice(0, 220)}</>}
          </p>
        </div>
        {m.comments_count > 0 && (
          <span className="mt-1 h-6 min-w-6 shrink-0 rounded-full bg-bc-blue px-2 text-center text-[13px] font-bold leading-6 text-white">
            {m.comments_count}
          </span>
        )}
      </Link>
    </li>
  );
}

export function MessageBoardPage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<Item[] | null>(null);
  const [drafts, setDrafts] = useState<Item[]>([]);
  const [sort, setSort] = useState<'newest' | 'activity' | 'alpha'>('newest');
  const [category, setCategory] = useState('');
  const [view, setView] = useState<'active' | 'archived' | 'trashed'>('active');
  const [error, setError] = useState('');

  const load = useCallback(() => {
    getProject(id).then(setProject, (e) => setError(apiErrorMessage(e, 'Could not load this project.')));
    listItems(id, 'message', { sort, status: view }).then(setMessages, (e) =>
      setError(apiErrorMessage(e, 'Could not load the messages.')),
    );
    listItems(id, 'message', { status: 'drafted' }).then(setDrafts, () => {});
  }, [id, sort, view]);
  useEffect(load, [load]);

  const title = toolTitle(project, 'message_board', 'Messages');
  const shown = (messages ?? []).filter((m) => !category || m.category === category);
  const used = [...new Set((messages ?? []).map((m) => m.category).filter(Boolean))];

  return (
    <ProjectsShell project={project} title={`${title} · ${project?.name ?? ''}`}>
      <Perma>
        <Crumbs
          project={project}
          crumbs={[{ label: project?.name ?? '…', to: `/p/${id}` }, { label: title }]}
          right={
            <Menu
              items={[
                {
                  label: view === 'active' ? 'Archived messages' : 'Back to the board',
                  onClick: () => setView(view === 'active' ? 'archived' : 'active'),
                },
                { label: 'Messages in the trash', onClick: () => setView('trashed'), hidden: view === 'trashed' },
              ]}
            />
          }
        />
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="bc-title text-2xl">
            {view === 'active' ? title : view === 'archived' ? 'Archived messages' : 'Trash'}
          </h1>
          <Link to={`/p/${id}/messages/new`} className="bc-btn bc-btn-primary ml-auto">
            ＋ New message
          </Link>
        </div>
        {drafts.length > 0 && view === 'active' && (
          <p className="mt-3 rounded-lg bg-bc-today px-3 py-2 text-[15px]">
            You have {drafts.length} draft{drafts.length === 1 ? '' : 's'}:{' '}
            {drafts.map((d, i) => (
              <span key={d.id}>
                {i > 0 && ', '}
                <Link to={`/i/${d.id}`} className="text-bc-blue underline">
                  {d.title}
                </Link>
              </span>
            ))}
          </p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-2 text-[15px]">
          <label className="flex items-center gap-1.5">
            <span className="text-bc-subtle">Sort</span>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as typeof sort)}
              className="bc-input w-auto py-1"
            >
              <option value="newest">Newest post</option>
              <option value="activity">Latest comment</option>
              <option value="alpha">A–Z</option>
            </select>
          </label>
          {used.length > 0 && (
            <label className="flex items-center gap-1.5">
              <span className="text-bc-subtle">Category</span>
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="bc-input w-auto py-1">
                <option value="">All</option>
                {used.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {error && (
          <p role="alert" className="mt-3 text-bc-unread">
            {error}
          </p>
        )}
        {messages && shown.length === 0 && (
          <div className="mt-6">
            <EmptyState title={view === 'active' ? 'No messages yet.' : 'Nothing here.'}>
              {view === 'active' &&
                'Post announcements, pitch ideas, ask questions — each one gets its own page and comments.'}
            </EmptyState>
          </div>
        )}
        <ul className="mt-2">
          {shown.map((m) => (
            <Row key={m.id} m={m} />
          ))}
        </ul>
      </Perma>
    </ProjectsShell>
  );
}

export function NewMessagePage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // Basecamp's "Schedule it": a draft that posts itself at this local date and time.
  const [scheduling, setScheduling] = useState(false);
  const [at, setAt] = useState('');
  const navigate = useNavigate();
  useEffect(() => {
    getProject(id).then(setProject, () => {});
  }, [id]);

  const save = async (draft: boolean, postAt?: string) => {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      const m = await createItem(id, 'message', {
        title: title.trim(),
        body,
        ...(category ? { category } : {}),
        ...(draft ? { status: 'drafted' as const } : {}),
        ...(postAt ? { post_at: new Date(postAt).toISOString() } : {}),
      });
      navigate(`/i/${m.id}`);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save the message.'));
      setBusy(false);
    }
  };
  const board = toolTitle(project, 'message_board', 'Messages');
  return (
    <ProjectsShell title="New message">
      <Perma>
        <Crumbs
          crumbs={[
            { label: project?.name ?? '…', to: `/p/${id}` },
            { label: board, to: `/p/${id}/messages` },
            { label: 'New message' },
          ]}
        />
        <form
          className="mx-auto max-w-3xl"
          onSubmit={(e) => {
            e.preventDefault();
            void save(false);
          }}
        >
          <div className="flex flex-wrap gap-2">
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
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Type a title…"
            aria-label="Title"
            maxLength={500}
            autoFocus
            className="bc-title mt-4 w-full border-0 bg-transparent text-[30px] placeholder:text-bc-faint focus:outline-none sm:text-[36px]"
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Write away… (Markdown works; @Name mentions someone)"
            aria-label="Message"
            rows={12}
            maxLength={20000}
            className="bc-input mt-3 text-[17px]"
          />
          <MentionPicker text={body} onPick={setBody} />
          {error && (
            <p role="alert" className="mt-2 text-bc-unread">
              {error}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="submit" className="bc-btn bc-btn-primary" disabled={!title.trim() || busy}>
              Post this message
            </button>
            <button type="button" className="bc-btn" disabled={!title.trim() || busy} onClick={() => void save(true)}>
              Save as a draft
            </button>
            <button
              type="button"
              className="bc-btn"
              aria-expanded={scheduling}
              onClick={() => setScheduling((v) => !v)}
            >
              🕓 Schedule it…
            </button>
            <Link to={`/p/${id}/messages`} className="bc-btn">
              Cancel
            </Link>
          </div>
          {scheduling && (
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-bc-wash p-3 text-[15px]">
              <span>Post it on</span>
              <input
                type="datetime-local"
                value={at}
                onChange={(e) => setAt(e.target.value)}
                aria-label="Post it at"
                className="bc-input w-auto py-1"
              />
              <button
                type="button"
                className="bc-btn bc-btn-primary bc-btn-sm"
                disabled={!title.trim() || !at || busy}
                onClick={() => void save(true, at)}
              >
                Schedule this message
              </button>
              <span className="w-full text-[13px] text-bc-subtle">
                It waits in your Drafts until then, and nobody else sees it.
              </span>
            </div>
          )}
        </form>
      </Perma>
    </ProjectsShell>
  );
}
