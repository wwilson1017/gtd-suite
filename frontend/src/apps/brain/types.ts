// Common Brain — the shapes backend/brain.py answers with.

export interface Memory {
  id: number;
  text: string;
  /** Only the person locks and unlocks; no AI can change a locked memory. */
  locked: boolean;
  status: 'active' | 'archived';
  /** Goes up on every change; a save naming an older one is refused (409). */
  version: number;
  /** The AI tool's name, or 'you' for the person in the app. */
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  /** On a write's answer only. */
  removed?: Removed[];
}

export interface PageSummary {
  id: number;
  /** Folders and a name: people/maya, daily/2026-10-24. */
  path: string;
  title: string;
  format: 'markdown' | 'html';
  status: 'active' | 'archived';
  version: number;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  size: number;
}

export interface Page extends Omit<PageSummary, 'size'> {
  body: string;
  /** On a write's answer only. */
  removed?: Removed[];
}

export interface Folder {
  folder: string;
  pages: number;
}

/** What a write blanked out: the kinds and how many, never the values. */
export interface Removed {
  kind: 'password' | 'key' | 'card number';
  count: number;
}

export interface SearchResult {
  memories: Memory[];
  /** Best match first, each with the stretch of its body around the first word found. */
  pages: (PageSummary & { snippet: string })[];
}

export interface Ai {
  name: string;
  first_seen_at: string;
  last_seen_at: string;
  /** When it finished "set up my brain"; null until then. */
  onboarded_at: string | null;
}

export interface Overview {
  memories: Memory[];
  pages: PageSummary[];
  folders: Folder[];
  ais: Ai[];
  /** null: no limit. */
  caps: { ais: number | null; memories: number; pages: number };
  /** Show the "add your email" nudge. */
  nudge: boolean;
  custom_instruction: string;
  /** What AIs searched for in the last 30 days and the brain still cannot answer, most asked first. */
  misses?: { query: string; asked: number; last: string }[];
}

export interface Change {
  pass: string;
  reason: string;
  kind: 'memory' | 'page';
  item_id: number;
  version: number;
  action: string;
  by: string;
  at: string;
  /** What it says now: a memory's text, or a page's "Title (path)". */
  what: string;
}

export interface Version {
  kind: 'memory' | 'page';
  item_id: number;
  version: number;
  action: string;
  by: string;
  at: string;
  status: 'active' | 'archived';
  text?: string;
  locked?: boolean;
  path?: string;
  title?: string;
  format?: string;
  body?: string;
}
