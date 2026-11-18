// Notes GTD — the notes API (backend/note_routes.py), through the todo app's fetch,
// which names the session's list (X-List) and handles signed-out, put-away and
// list-changed answers the same way for every app.
import { todoFetch } from '../todo-gtd/api';
import type { Note, NotePage, TagCount } from './types';

function send<T>(method: string, sub: string, body: unknown): Promise<T> {
  return todoFetch<T>(sub, { method, body: JSON.stringify(body) });
}

/** One page of notes: pinned first, then (with `q`) title hits, then the newest change. */
export function listNotes(params: {
  q?: string;
  tag?: string;
  status?: Note['status'];
  offset?: number;
}): Promise<NotePage> {
  const query = new URLSearchParams({ limit: '100' });
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, String(value));
  return todoFetch<NotePage>(`/notes?${query}`);
}

export function getNote(id: number): Promise<Note> {
  return todoFetch<Note>(`/notes/${id}`);
}

export function createNote(fields: Partial<Pick<Note, 'title' | 'body' | 'color' | 'pinned'>>): Promise<Note> {
  return send('POST', '/notes', fields);
}

/** A title or body change must name `version`; with it, any change is refused (409)
 *  when the note changed since it was read. */
export function updateNote(
  id: number,
  fields: Partial<Pick<Note, 'title' | 'body' | 'color' | 'pinned' | 'status'>> & { version?: number },
): Promise<Note> {
  return send('PUT', `/notes/${id}`, fields);
}

/** Every tag on the active notes, with how many carry it. */
export function noteTags(): Promise<TagCount[]> {
  return todoFetch<{ tags: TagCount[] }>('/notes/tags').then((r) => r.tags);
}
