// Notes GTD — the shapes backend/notes.py answers with.

export const NOTE_COLORS = ['', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'gray'] as const;
export type NoteColor = (typeof NOTE_COLORS)[number];

export interface Note {
  id: number;
  title: string;
  /** Markdown. Checklists are `- [ ]` items; tags are the `#words` in it. */
  body: string;
  /** Read from the body's #hashtags by the server; never written directly. */
  tags: string[];
  color: NoteColor;
  pinned: boolean;
  status: 'active' | 'archived';
  /** Goes up on every change; a title or body save names it, and a stale one is refused (409). */
  version: number;
  source: 'ui' | 'agent';
  source_client: string | null;
  /** The AI tool behind the last write; null when it was made in the app. */
  edited_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotePage {
  notes: Note[];
  count: number;
  next_offset: number | null;
}

export interface TagCount {
  tag: string;
  count: number;
}
