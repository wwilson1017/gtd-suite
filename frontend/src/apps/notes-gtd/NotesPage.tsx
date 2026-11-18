// Notes GTD — the grid: the composer, search and tag filters, then the notes, pinned
// first (Keep's way). Archive is the same page over archived notes. It loads again
// whenever the window comes back into focus, so what an agent wrote shows up.
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import SearchInput from '../../shared/search/SearchInput';
import { getNote, listNotes, noteTags, updateNote } from './api';
import { Composer } from './Composer';
import { NoteCard } from './NoteCard';
import { NoteEditor } from './NoteEditor';
import { NotesShell } from './NotesShell';
import { toggleTask } from './toggleTask';
import type { Note, TagCount } from './types';

const h2Cls = 'mb-2 mt-6 text-xs font-heading font-semibold uppercase tracking-wide text-muted';

export function NotesPage({ status }: { status: Note['status'] }) {
  const archive = status === 'archived';
  const base = archive ? '/archive' : '';
  const [q, setQ] = useState('');
  const [tag, setTag] = useState('');
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [error, setError] = useState('');
  // A note opened by its address that the loaded page does not hold.
  const [fetched, setFetched] = useState<Note | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams();
  const openId = id ? Number(id) : null;

  const load = useCallback(() => {
    listNotes({ q, tag, status }).then(
      (page) => {
        setNotes(page.notes);
        setNext(page.next_offset);
        setError('');
      },
      (e) => setError(apiErrorMessage(e, 'Could not load your notes.')),
    );
    noteTags().then(setTags, () => {});
  }, [q, tag, status]);
  useEffect(load, [load]);
  useEffect(() => {
    window.addEventListener('focus', load);
    return () => window.removeEventListener('focus', load);
  }, [load]);

  const more = () => {
    if (next === null) return;
    listNotes({ q, tag, status, offset: next }).then(
      (page) => {
        setNotes((list) => [...(list ?? []), ...page.notes]);
        setNext(page.next_offset);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load more notes.')),
    );
  };

  const listed = openId === null ? null : (notes?.find((n) => n.id === openId) ?? null);
  const missing = openId !== null && notes !== null && listed === null;
  useEffect(() => {
    if (missing && openId !== null) getNote(openId).then(setFetched, () => navigate(base || '/', { replace: true }));
  }, [missing, openId, base, navigate]);
  const opened = listed ?? (fetched?.id === openId ? fetched : null);

  const open = (note: Note) => navigate(`${base}/n/${note.id}`, { state: { grid: true } });
  const close = () => {
    // Opened from the grid: go back, so the back button and Close agree.
    if ((location.state as { grid?: boolean } | null)?.grid) navigate(-1);
    else navigate(base || '/', { replace: true });
    load();
  };

  const replace = (note: Note) => setNotes((list) => list?.map((n) => (n.id === note.id ? note : n)) ?? list);

  const change = async (note: Note, fields: Partial<Pick<Note, 'pinned' | 'color' | 'status'>>) => {
    try {
      await updateNote(note.id, fields);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save. Try again.'));
    }
    load();
  };

  /** Tick a checklist item on a card: the source changes, named with the card's version. */
  const toggle = async (note: Note, offset: number) => {
    try {
      replace(await updateNote(note.id, { body: toggleTask(note.body, offset), version: note.version }));
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? 'That note changed somewhere else; this is the latest. Tick it again if you still want to.'
          : apiErrorMessage(e, 'Could not save. Try again.'),
      );
      load();
    }
  };

  const pinned = archive ? [] : (notes ?? []).filter((n) => n.pinned);
  const others = archive ? (notes ?? []) : (notes ?? []).filter((n) => !n.pinned);
  const grid = (list: Note[]) => (
    <div className="columns-1 gap-3 sm:columns-2 lg:columns-3 xl:columns-4">
      {list.map((n) => (
        <NoteCard
          key={n.id}
          note={n}
          onOpen={() => open(n)}
          onToggle={(offset) => void toggle(n, offset)}
          onChange={(fields) => void change(n, fields)}
        />
      ))}
    </div>
  );

  return (
    <NotesShell title={archive ? 'Archive' : undefined}>
      <div className="mx-auto max-w-shell">
        {!archive && (
          <div className="mx-auto max-w-xl">
            <Composer onCreated={load} />
          </div>
        )}
        <SearchInput
          value={q}
          onChange={setQ}
          className="mt-4 max-w-md"
          placeholder={archive ? 'Search the archive' : 'Search notes'}
        />
        {!archive && tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <button
                key={t.tag}
                type="button"
                aria-pressed={tag === t.tag}
                onClick={() => setTag(tag === t.tag ? '' : t.tag)}
                className={`rounded-full border px-2.5 py-0.5 text-xs ${
                  tag === t.tag
                    ? 'border-charcoal bg-charcoal text-cream'
                    : 'border-line bg-cream text-charcoal hover:bg-sand'
                }`}
              >
                #{t.tag} <span className="opacity-60">{t.count}</span>
              </button>
            ))}
          </div>
        )}
        {error && (
          <p role="alert" className="mt-3 text-sm text-brand-ink">
            {error}
          </p>
        )}
        {notes && notes.length === 0 && (
          <p className="mt-8 text-center text-sm text-muted">
            {q || tag
              ? 'No notes match.'
              : archive
                ? 'Nothing archived.'
                : 'No notes yet. Take one above, or connect your AI under Connect so it can keep notes here too.'}
          </p>
        )}
        {pinned.length > 0 && (
          <>
            <h2 className={h2Cls}>Pinned</h2>
            {grid(pinned)}
          </>
        )}
        {pinned.length > 0 && others.length > 0 && <h2 className={h2Cls}>Others</h2>}
        <div className={pinned.length ? '' : 'mt-4'}>{grid(others)}</div>
        {next !== null && (
          <button type="button" onClick={more} className="mt-2 text-sm text-muted underline">
            Show more
          </button>
        )}
      </div>
      {opened && <NoteEditor key={opened.id} note={opened} onClose={close} onChanged={replace} />}
    </NotesShell>
  );
}
