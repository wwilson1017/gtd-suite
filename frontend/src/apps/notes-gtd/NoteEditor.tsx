// Notes GTD — one note, open: its title and markdown body, saved as you go (after
// a pause in typing, on leaving a field, on close). Writes run one at a time, each
// naming the version the last one returned, so a save never overwrites what an
// agent wrote meanwhile: that answer is a 409, and the person picks whose text
// stays. Their draft stays on screen until they do.
import { useEffect, useId, useRef, useState } from 'react';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { getNote, updateNote } from './api';
import { ColorPicker, editedBy, NOTE_BG, quickCls } from './NoteCard';
import type { Note } from './types';

/** How long typing must pause before the draft saves. */
const PAUSE_MS = 1500;

type Flags = Partial<Pick<Note, 'pinned' | 'color' | 'status'>>;

interface Props {
  note: Note;
  onClose: () => void;
  /** The note as the server now holds it, after each write. */
  onChanged: (note: Note) => void;
}

export function NoteEditor({ note: opened, onClose, onChanged }: Props) {
  const [note, setNote] = useState(opened);
  const [title, setTitle] = useState(opened.title);
  const [body, setBody] = useState(opened.body);
  // The note as it stands after someone else's change, while the person decides.
  const [conflict, setConflict] = useState<Note | null>(null);
  const [colors, setColors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const titleId = useId();
  // A queued write reads these when it runs, not when it was queued.
  const server = useRef(opened);
  const draft = useRef({ title: opened.title, body: opened.body });
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  // Bumped by a refused write: writes queued behind it are dropped.
  const generation = useRef(0);
  const halted = useRef(false);

  const adopt = (next: Note) => {
    server.current = next;
    setNote(next);
    onChanged(next);
  };

  /** What the draft changes, against the server's copy (the server trims, so this does too). */
  const changes = () => {
    const out: { title?: string; body?: string } = {};
    if (draft.current.title.trim() !== server.current.title.trim()) out.title = draft.current.title.trim();
    if (draft.current.body.trim() !== server.current.body.trim()) out.body = draft.current.body;
    return out;
  };

  const attempt = async (flags: Flags): Promise<boolean> => {
    const fields = { ...changes(), ...flags };
    if (Object.keys(fields).length === 0) return true;
    setBusy(true);
    setError('');
    try {
      adopt(await updateNote(opened.id, { ...fields, version: server.current.version }));
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        generation.current += 1;
        halted.current = true;
        try {
          setConflict(await getNote(opened.id));
        } catch (err) {
          halted.current = false;
          setError(apiErrorMessage(err, 'This note changed elsewhere and could not be reloaded. Try again.'));
        }
      } else {
        setError(apiErrorMessage(e, 'Could not save. Try again.'));
      }
      return false;
    } finally {
      setBusy(false);
    }
  };

  /** Queue a write of the draft (and `flags`); resolves to whether it was taken. */
  const save = (flags: Flags = {}): Promise<boolean> => {
    const mine = generation.current;
    const job = queue.current.then(() => (mine === generation.current && !halted.current ? attempt(flags) : false));
    queue.current = job;
    return job;
  };

  const close = async () => {
    if (await save()) onClose();
  };

  // Save once typing pauses; `save` reads the refs, so only typing restarts the wait.
  useEffect(() => {
    if (title === server.current.title && body === server.current.body) return;
    const timer = setTimeout(() => void save(), PAUSE_MS);
    return () => clearTimeout(timer);
  }, [title, body]);

  // Leaving without close (browser Back) still saves the draft.
  useEffect(
    () => () => {
      void save();
    },
    [],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') void close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const edit = (field: 'title' | 'body', value: string) => {
    draft.current = { ...draft.current, [field]: value };
    (field === 'title' ? setTitle : setBody)(value);
  };

  const useTheirs = () => {
    if (!conflict) return;
    adopt(conflict);
    draft.current = { title: conflict.title, body: conflict.body };
    setTitle(conflict.title);
    setBody(conflict.body);
    setConflict(null);
    halted.current = false;
  };

  const keepMine = () => {
    if (!conflict) return;
    server.current = conflict;
    setNote(conflict);
    setConflict(null);
    halted.current = false;
    void save();
  };

  const archived = note.status === 'archived';
  const who = conflict?.edited_by ? `by ${conflict.edited_by}` : 'in another window or device';

  return (
    <div
      className="fixed inset-0 z-30 flex bg-black/40 sm:items-center sm:justify-center sm:p-4"
      onClick={() => void close()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`flex h-full w-full flex-col overflow-y-auto p-4 shadow-xl sm:h-auto sm:max-h-[90vh] sm:max-w-2xl sm:rounded-2xl ${NOTE_BG[note.color]}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-2">
          <input
            id={titleId}
            value={title}
            maxLength={500}
            placeholder="Title"
            aria-label="Title"
            onChange={(e) => edit('title', e.target.value)}
            onBlur={() => void save()}
            className="min-w-0 flex-1 rounded-lg bg-transparent px-1 py-1 font-heading text-lg font-bold text-charcoal focus:outline-none"
          />
          <button
            type="button"
            onClick={() => void close()}
            aria-label="Close"
            className="rounded-lg px-2 py-1 text-xl leading-none text-muted hover:text-charcoal"
          >
            &times;
          </button>
        </div>

        {conflict && (
          <div role="alert" className="mt-2 rounded-lg border border-brand bg-cream p-3 text-sm text-charcoal">
            <p>Changed {who} while you were editing. Your text is still here.</p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={useTheirs}
                className="rounded-lg border border-line bg-cream px-3 py-1.5 font-heading hover:bg-sand"
              >
                Use theirs
              </button>
              <button
                type="button"
                onClick={keepMine}
                className="rounded-lg bg-brand-dark px-3 py-1.5 font-heading text-white hover:bg-brand-deep"
              >
                Keep mine
              </button>
            </div>
          </div>
        )}

        <textarea
          value={body}
          onChange={(e) => edit('body', e.target.value)}
          onBlur={() => void save()}
          aria-label="Note"
          maxLength={20000}
          rows={14}
          placeholder="Markdown. - [ ] makes a checklist item; #words are tags."
          className="mt-2 min-h-[40vh] w-full flex-1 resize-y rounded-lg bg-transparent px-1 py-1 font-mono text-base leading-relaxed text-charcoal focus:outline-none sm:text-[13px]"
        />

        {error && (
          <p role="alert" className="mt-2 text-sm text-brand-ink">
            {error}
          </p>
        )}
        {colors && (
          <div className="mt-2">
            <ColorPicker
              value={note.color}
              onPick={(c) => {
                setColors(false);
                void save({ color: c });
              }}
            />
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-1">
          {!archived && (
            <button type="button" className={quickCls} onClick={() => void save({ pinned: !note.pinned })}>
              {note.pinned ? 'Unpin' : 'Pin'}
            </button>
          )}
          <button type="button" className={quickCls} aria-expanded={colors} onClick={() => setColors(!colors)}>
            Colour
          </button>
          <button
            type="button"
            className={quickCls}
            onClick={() =>
              void save({ status: archived ? 'active' : 'archived' }).then((ok) => {
                if (ok && !archived) onClose();
              })
            }
          >
            {archived ? 'Restore' : 'Archive'}
          </button>
          <span className="ml-auto text-xs text-muted">{busy ? 'Saving…' : editedBy(note)}</span>
        </div>
      </div>
    </div>
  );
}
