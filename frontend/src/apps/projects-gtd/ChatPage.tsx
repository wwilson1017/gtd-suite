// Projects GTD — Chat (Basecamp 5's, once Campfire): the project's room for quick
// talk, oldest at the top and the newest by the box you type in. An open page
// asks for new lines every few seconds; your AI tools talk here too. Enter sends,
// Shift+Enter starts a new line. And External links (Basecamp's Doors): the
// project's ways out to the tools kept elsewhere.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { boostItem, createItem, getChat, getProject, listItems, removeBoost, updateItem } from './api';
import { ProjectsShell } from './ProjectsShell';
import type { Item, Project } from './types';
import { Avatar, Body, Boosts, Crumbs, EmptyState, MentionPicker, Menu, Perma, when } from './ui';

const POLL_MS = 4000;
// Every so many polls, the latest page is read whole, so boosts, and lines put away,
// show without a reload.
// simplification: only the latest page is refreshed this way; a change cursor on the
// server would catch changes to older lines too.
const REFRESH_EVERY = 8;

export function ChatPage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [lines, setLines] = useState<Item[]>([]);
  const [earlier, setEarlier] = useState(false);
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [previousId, setPreviousId] = useState(id);
  if (id !== previousId) {
    setPreviousId(id);
    setLines([]);
    setError('');
  }
  const latest = useRef(0);
  const polls = useRef(0);
  // Bumped when the room changes: an answer for the room left behind is dropped.
  const generation = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    getProject(id).then(setProject, () => {});
  }, [id]);

  const poll = useCallback(() => {
    const mine = generation.current;
    const read = async () => {
      if (!latest.current) {
        // the room's latest page, when it opens
        const room = await getChat(id);
        if (mine !== generation.current) return;
        setError('');
        setLines(room.lines);
        setEarlier(room.earlier);
        latest.current = room.latest;
        setTimeout(() => bottom.current?.scrollIntoView({ block: 'end' }), 0);
        return;
      }
      // Catching up: only this moves the cursor, so no line is ever skipped.
      const fresh = await getChat(id, { since: latest.current });
      if (mine !== generation.current) return;
      setError('');
      if (fresh.lines.length) {
        setLines((old) => [...old, ...fresh.lines.filter((l) => !old.some((o) => o.id === l.id))]);
        latest.current = Math.max(latest.current, fresh.latest);
        setTimeout(() => bottom.current?.scrollIntoView({ block: 'end' }), 0);
      }
      // Now and then the latest page is reread, for boosts and lines put away.
      if (++polls.current % REFRESH_EVERY === 0) {
        const page = await getChat(id);
        if (mine !== generation.current) return;
        const first = page.lines[0]?.id;
        const last = page.lines.at(-1)?.id ?? latest.current;
        setLines((old) => [
          ...(page.earlier && first !== undefined ? old.filter((l) => l.id < first) : []),
          ...page.lines,
          ...old.filter((l) => l.id > last),
        ]);
      }
    };
    return read().catch((e) => {
      if (mine === generation.current) setError(apiErrorMessage(e, 'Could not load the chat.'));
    });
  }, [id]);
  // A layout effect runs in the same commit as the new room's first render, before any
  // answer still in flight for the old room can land, so those answers are dropped.
  useLayoutEffect(() => {
    generation.current += 1;
    latest.current = 0;
    polls.current = 0;
  }, [id]);
  useEffect(() => {
    void poll();
    const timer = window.setInterval(() => {
      if (!document.hidden) void poll();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [poll]);

  const send = async () => {
    const body = text.trim();
    if (!body) return;
    setText('');
    try {
      await createItem(id, 'chat_line', { body });
      await poll();
    } catch (e) {
      setText(body);
      setError(apiErrorMessage(e, 'That did not send.'));
    }
  };
  const older = async () => {
    const mine = generation.current;
    const room = await getChat(id, { before: lines[0]?.id });
    if (mine !== generation.current) return; // the room changed meanwhile
    setLines((old) => [...room.lines.filter((l) => !old.some((o) => o.id === l.id)), ...old]);
    setEarlier(room.earlier);
  };
  const refresh = (lineId: number) =>
    getChat(id, { before: lineId + 1 }).then((room) => {
      const fresh = room.lines.find((l) => l.id === lineId);
      if (fresh) setLines((old) => old.map((l) => (l.id === lineId ? fresh : l)));
    });
  const title = project?.dock.find((t) => t.tool === 'chat')?.title ?? 'Chat';
  return (
    <ProjectsShell project={project} title={`${title} · ${project?.name ?? ''}`}>
      <Perma>
        <Crumbs project={project} crumbs={[{ label: project?.name ?? '…', to: `/p/${id}` }, { label: title }]} />
        <h1 className="bc-title text-2xl">{title}</h1>
        <div className="mx-auto mt-4 max-w-3xl">
          {earlier && (
            <p className="text-center">
              <button type="button" className="text-[14px] text-bc-blue underline" onClick={() => void older()}>
                Earlier lines
              </button>
            </p>
          )}
          {lines.length === 0 && !error && (
            <EmptyState title="Nobody has said anything yet.">Say hello. Your AI tools can chat here too.</EmptyState>
          )}
          <ol className="mt-2 space-y-1" aria-label="Chat lines">
            {lines.map((l, i) => {
              const same =
                i > 0 &&
                lines[i - 1].creator?.id === l.creator?.id &&
                new Date(l.created_at).getTime() - new Date(lines[i - 1].created_at).getTime() < 5 * 60_000;
              return (
                <li key={l.id} className={`group flex gap-3 ${same ? '' : 'mt-3'}`}>
                  <span className="w-8 shrink-0">{!same && <Avatar person={l.creator} size={32} />}</span>
                  <div className="min-w-0 flex-1">
                    {!same && (
                      <p className="text-[13px]">
                        <b>{l.creator?.name ?? 'Someone'}</b>{' '}
                        <span className="text-bc-subtle">{when(l.created_at)}</span>
                      </p>
                    )}
                    <Body text={l.body} />
                    {/* The boost button shows on hover, unless the line has boosts already. */}
                    <div
                      className={(l.boosts?.length ?? 0) > 0 ? '' : 'hidden group-hover:block group-focus-within:block'}
                    >
                      <Boosts
                        boosts={l.boosts ?? []}
                        onBoost={(c) => boostItem(l.id, c).then(() => refresh(l.id))}
                        onRemove={(b) => removeBoost(b).then(() => refresh(l.id))}
                      />
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
          <div ref={bottom} />
          {error && (
            <p role="alert" className="mt-2 text-bc-unread">
              {error}
            </p>
          )}
          <form
            className="sticky bottom-14 mt-4 flex gap-2 bg-bc-canvas py-2"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={2}
              maxLength={20000}
              aria-label="Say something"
              placeholder="Say something… (Enter sends, Shift+Enter for a new line)"
              className="bc-input text-[16px]"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button type="submit" className="bc-btn bc-btn-primary self-end" disabled={!text.trim()}>
              Send
            </button>
          </form>
          <MentionPicker text={text} onPick={setText} />
        </div>
      </Perma>
    </ProjectsShell>
  );
}

export function DoorsPage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [doors, setDoors] = useState<Item[]>([]);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(() => {
    listItems(id, 'door').then(setDoors, (e) => setError(apiErrorMessage(e, 'Could not load the links.')));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    getProject(id).then(setProject, () => {});
  }, [id]);
  const add = async () => {
    try {
      await createItem(id, 'door', { title: title.trim(), url: url.trim() });
      setTitle('');
      setUrl('');
      setAdding(false);
      setError('');
      load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not add the link.'));
    }
  };
  const heading = project?.dock.find((t) => t.tool === 'doors')?.title ?? 'External links';
  return (
    <ProjectsShell project={project} title={`${heading} · ${project?.name ?? ''}`}>
      <Perma>
        <Crumbs project={project} crumbs={[{ label: project?.name ?? '…', to: `/p/${id}` }, { label: heading }]} />
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="bc-title mr-auto text-2xl">{heading}</h1>
          <button type="button" className="bc-btn bc-btn-primary" onClick={() => setAdding(true)}>
            ＋ Add a link
          </button>
        </div>
        <p className="text-bc-subtle">
          The other places this project's work lives: a Figma file, a shared drive, a repo, a booking page.
        </p>
        {adding && (
          <form
            className="mt-3 flex flex-wrap gap-2 rounded-lg border border-bc-line p-3"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
              maxLength={500}
              placeholder="What it is, e.g. Brand files"
              aria-label="Name"
              className="bc-input w-60"
            />
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              maxLength={500}
              placeholder="https://…"
              aria-label="Address"
              className="bc-input min-w-0 flex-1"
            />
            <button type="submit" className="bc-btn bc-btn-primary" disabled={!title.trim() || !url.trim()}>
              Add it
            </button>
            <button type="button" className="bc-btn" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </form>
        )}
        {error && (
          <p role="alert" className="mt-2 text-bc-unread">
            {error}
          </p>
        )}
        {doors.length === 0 && !adding && (
          <div className="mt-6">
            <EmptyState title="No external links yet." />
          </div>
        )}
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {doors.map((d) => (
            <li
              key={d.id}
              className="flex items-start gap-2 rounded-lg border border-bc-line p-3 hover:border-bc-faint"
            >
              <a href={d.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1">
                <span className="block font-bold">🚪 {d.title} ↗</span>
                <span className="block truncate text-[13px] text-bc-subtle">{d.url}</span>
              </a>
              <Menu
                items={[{ label: 'Archive', onClick: () => void updateItem(d.id, { status: 'archived' }).then(load) }]}
              />
            </li>
          ))}
        </ul>
      </Perma>
    </ProjectsShell>
  );
}
