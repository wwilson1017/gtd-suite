// Notes GTD — Keep's "Take a note…" box: tap it for a title and a body; closing it
// (Close, Escape, or tapping away) saves the note if anything was typed, and
// nothing at all if not.
import { useRef, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { createNote } from './api';
import type { Note } from './types';

const fieldCls = 'w-full bg-transparent px-1 py-1 text-charcoal focus:outline-none';

export function Composer({ onCreated }: { onCreated: (note: Note) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const busy = useRef(false);
  // Fields lock while the note is on its way, so nothing typed is left out of it.
  const [saving, setSaving] = useState(false);

  const close = async () => {
    if (busy.current) return;
    if (!title.trim() && !body.trim()) {
      setOpen(false);
      return;
    }
    busy.current = true;
    setSaving(true);
    setError('');
    try {
      onCreated(await createNote({ title: title.trim(), body }));
      setTitle('');
      setBody('');
      setOpen(false);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save the note. Try again.'));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="block w-full rounded-xl border border-line bg-cream px-4 py-3 text-left text-muted shadow-sm hover:border-charcoal"
      >
        Take a note…
      </button>
    );
  }
  return (
    <div
      className="rounded-xl border border-line bg-cream p-3 shadow-sm"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) void close();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') void close();
      }}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        aria-label="Title"
        maxLength={500}
        readOnly={saving}
        className={`${fieldCls} font-heading font-bold`}
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        autoFocus
        rows={4}
        placeholder="Take a note… (markdown; - [ ] for a checklist, #tags anywhere)"
        aria-label="Note"
        maxLength={20000}
        readOnly={saving}
        className={`${fieldCls} resize-y text-base sm:text-sm`}
      />
      {error && (
        <p role="alert" className="mt-1 text-sm text-brand-ink">
          {error}
        </p>
      )}
      <div className="mt-1 flex justify-end">
        <button
          type="button"
          onClick={() => void close()}
          className="rounded-lg px-3 py-1.5 font-heading text-sm text-charcoal hover:bg-sand"
        >
          Close
        </button>
      </div>
    </div>
  );
}
