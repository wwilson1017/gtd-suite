// Notes GTD — one note in the grid: its colour, title, the start of its body
// (rendered, with live checkboxes), its tags, who last changed it, and the quick
// actions. Tapping it opens the editor.
import { useState, type MouseEvent } from 'react';
import { formatAge } from '../todo-gtd/util';
import { Markdown } from './Markdown';
import { NOTE_COLORS, type Note, type NoteColor } from './types';

/** Each colour's surface; literal class names, so Tailwind sees them. */
export const NOTE_BG: Record<NoteColor, string> = {
  '': 'bg-cream',
  red: 'bg-note-red',
  orange: 'bg-note-orange',
  yellow: 'bg-note-yellow',
  green: 'bg-note-green',
  teal: 'bg-note-teal',
  blue: 'bg-note-blue',
  purple: 'bg-note-purple',
  gray: 'bg-note-gray',
};

export const quickCls =
  'rounded-lg px-2 py-1 text-xs font-heading text-muted hover:bg-black/5 hover:text-charcoal disabled:opacity-40';

/** A row of swatches; picking one calls `onPick`. */
export function ColorPicker({ value, onPick }: { value: NoteColor; onPick: (c: NoteColor) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Colour">
      {NOTE_COLORS.map((c) => (
        <button
          key={c || 'none'}
          type="button"
          aria-label={c || 'No colour'}
          aria-pressed={c === value}
          onClick={(e) => {
            e.stopPropagation();
            onPick(c);
          }}
          className={`h-6 w-6 rounded-full border ${NOTE_BG[c]} ${c === value ? 'border-charcoal' : 'border-line'}`}
        />
      ))}
    </div>
  );
}

/** "edited by Claude · 3d ago", when an AI tool made the last change. */
export function editedBy(note: Note): string {
  if (!note.edited_by) return '';
  const age = formatAge(note.updated_at);
  return `edited by ${note.edited_by} · ${age === 'today' ? 'today' : `${age} ago`}`;
}

interface Props {
  note: Note;
  onOpen: () => void;
  onToggle: (offset: number) => void;
  onChange: (fields: Partial<Pick<Note, 'pinned' | 'color' | 'status'>>) => void;
}

export function NoteCard({ note, onOpen, onToggle, onChange }: Props) {
  const [colors, setColors] = useState(false);
  const archived = note.status === 'archived';
  const stop = (fn: () => void) => (e: MouseEvent) => {
    e.stopPropagation();
    fn();
  };
  return (
    <article
      onClick={onOpen}
      className={`mb-3 cursor-pointer break-inside-avoid rounded-xl border border-line-faint p-3 hover:border-line ${NOTE_BG[note.color]}`}
    >
      {note.title && <h3 className="mb-1 font-heading text-base font-bold text-charcoal">{note.title}</h3>}
      <div className="max-h-72 overflow-hidden">
        <Markdown body={note.body} onToggle={archived ? undefined : onToggle} />
      </div>
      {note.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {note.tags.map((t) => (
            <span key={t} className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-muted">
              #{t}
            </span>
          ))}
        </div>
      )}
      {note.edited_by && <p className="mt-2 text-xs text-muted">{editedBy(note)}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {!archived && (
          <button type="button" className={quickCls} onClick={stop(() => onChange({ pinned: !note.pinned }))}>
            {note.pinned ? 'Unpin' : 'Pin'}
          </button>
        )}
        <button type="button" className={quickCls} aria-expanded={colors} onClick={stop(() => setColors(!colors))}>
          Colour
        </button>
        <button
          type="button"
          className={quickCls}
          onClick={stop(() => onChange({ status: archived ? 'active' : 'archived' }))}
        >
          {archived ? 'Restore' : 'Archive'}
        </button>
      </div>
      {colors && (
        <div className="mt-2">
          <ColorPicker
            value={note.color}
            onPick={(c) => {
              setColors(false);
              onChange({ color: c });
            }}
          />
        </div>
      )}
    </article>
  );
}
