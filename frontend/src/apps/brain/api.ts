// Common Brain — the brain API (backend/brain_routes.py), through the todo app's fetch,
// which names the session's list (X-List) and handles signed-out, put-away and
// list-changed answers the same way for every app.
import { todoFetch } from '../todo-gtd/api';
import { ApiError } from '../../core/api/client';
import { selectedBrain, brainGeneration, refreshBrains, selectBrain } from '../todo-gtd/brainSelection';
import type { Change, Memory, Overview, Page, PageSummary, Removed, SearchResult, Version } from './types';

/** Capture before any await. An override lets uploads finish in their starting brain. */
export async function brainFetch<T>(
  sub: string,
  options: RequestInit = {},
  override?: number | null,
  responseType: 'json' | 'blob' = 'json',
): Promise<T> {
  const id = override === undefined ? selectedBrain() : override;
  const generation = brainGeneration();
  try {
    const result = await todoFetch<T>(
      sub,
      { ...options, headers: { ...options.headers, ...(id === null ? {} : { 'X-Brain': String(id) }) } },
      responseType,
    );
    if (override === undefined && generation !== brainGeneration()) throw new Error('The selected brain changed.');
    return result;
  } catch (e) {
    if (
      e instanceof ApiError &&
      e.status === 409 &&
      typeof e.detail === 'object' &&
      e.detail !== null &&
      'brain_gone' in e.detail &&
      id === selectedBrain()
    ) {
      const data = await getBrains();
      if (generation !== brainGeneration()) throw e;
      refreshBrains(data.brains);
      const first = data.brains.find((b) => b.status === 'active');
      if (first) selectBrain(first.id, 'That brain is no longer available. Opened your first brain.');
    }
    throw e;
  }
}

function send<T>(method: string, sub: string, body?: unknown, brain?: number | null): Promise<T> {
  return brainFetch<T>(`/brain${sub}`, { method, body: body === undefined ? undefined : JSON.stringify(body) }, brain);
}

export const getOverview = () => brainFetch<Overview>('/brain');
export const getArchive = () => brainFetch<{ memories: Memory[]; pages: PageSummary[] }>('/brain/archive');
export const getChanges = (limit = 200) =>
  brainFetch<{ changes: Change[] }>(`/brain/changes?limit=${limit}`).then((r) => r.changes);
export const getMemory = (id: number) => brainFetch<Memory>(`/brain/memories/${id}`);
export const getPage = (id: number) => brainFetch<Page>(`/brain/pages/${id}`);
export const getHistory = (kind: 'memory' | 'page', id: number) =>
  brainFetch<{ versions: Version[] }>(`/brain/history/${kind}/${id}`).then((r) => r.versions);
export const searchBrain = (q: string) => brainFetch<SearchResult>(`/brain/search?q=${encodeURIComponent(q)}`);
/** Where a page's [[links]] lead; a target that leads nowhere is left out. */
export const resolveLinks = (targets: string[]) =>
  send<{ links: Record<string, { kind: 'page' | 'file'; id: number; path: string }> }>('POST', '/resolve', {
    targets,
  }).then((r) => r.links);

export const addMemory = (text: string) =>
  send<{ memory: Memory | null; skipped: { text: string; reason: string }[]; removed: Removed[] }>(
    'POST',
    '/memories',
    { text },
  );
/** With `version`, a memory changed since it was read is refused (409). */
export const updateMemory = (
  id: number,
  fields: Partial<Pick<Memory, 'text' | 'locked' | 'status'>> & { version?: number; review_on?: string },
) => send<Memory>('PUT', `/memories/${id}`, fields);
export const createPage = (fields: { path: string; title?: string; body?: string; format?: string }) =>
  send<Page>('POST', '/pages', fields);
export const updatePage = (
  id: number,
  fields: Partial<Pick<Page, 'title' | 'body' | 'format' | 'path' | 'status'>> & { version?: number },
) => send<Page>('PUT', `/pages/${id}`, fields);
export const restore = (kind: 'memory' | 'page', id: number, version: number) =>
  send<Memory | Page>('POST', '/restore', { kind, id, version });
/** For good, with its whole history: the person's own, never an AI's. */
export const forget = (kind: 'memory' | 'page', id: number) =>
  send<{ forgotten: string; id: number; versions: number }>(
    'POST',
    `/${kind === 'memory' ? 'memories' : 'pages'}/${id}/forget`,
  );
export const sharePage = (id: number) => send<{ address: string }>('POST', `/pages/${id}/share`);

/** A program key (backend/keys.py) as listed: never the key itself. */
export interface ProgramKey {
  id: number;
  name: string;
  last4: string;
  kind?: 'key' | 'link';
  brains?: number[];
  apps: 'brain' | 'all';
  access: 'read' | 'write';
  folders: string[];
  created_at: string;
  last_used_at: string | null;
  /** Its end date, if it was given one; past it the key is `expired` and works no more. */
  expires_at?: string | null;
  expired?: boolean;
}
/** A key just made: the only answer that carries the key. */
export type NewProgramKey = ProgramKey & { key: string; link?: string };
export const getKeys = () => todoFetch<{ keys: ProgramKey[] }>('/keys').then((r) => r.keys);
export const createKey = (
  fields: Pick<ProgramKey, 'name' | 'apps' | 'access' | 'folders' | 'brains' | 'kind'> & { days?: number },
) => todoFetch<NewProgramKey>('/keys', { method: 'POST', body: JSON.stringify(fields) });
export const revokeKey = (id: number) => todoFetch<{ ok: boolean }>(`/keys/${id}/revoke`, { method: 'POST' });

/** A file in the brain (backend/files.py); its bytes are in the file store. */
export interface BrainFile {
  id: number;
  /** Folders and a name, in any case and characters: raw/2026/Scan 1.pdf. */
  path: string;
  size: number;
  sha256: string;
  content_type: string;
  status: 'active' | 'archived';
  created_by: string;
  created_at: string;
  updated_at: string;
}
/** `on`: the server has a file store. Sizes in bytes. */
export interface FilesView {
  on: boolean;
  used: number;
  quota: number;
  files: BrainFile[];
}
export const getFiles = () => brainFetch<FilesView>('/brain/files');
export const setFileStatus = (id: number, status: BrainFile['status']) =>
  send<BrainFile>('PUT', `/files/${id}`, { status });
/** For good: every version at its path. */
export const forgetFile = (id: number) => send<{ forgotten: string; versions: number }>('POST', `/files/${id}/forget`);

export const BROWSER_MAX_BYTES = 500_000_000;

/** The SHA-256 the store checks an upload against, as hex. */
export async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

interface Reserved {
  id: number;
  upload: { url: string; headers: Record<string, string> };
}

/** Upload into `folder`, 100 at a time: reserve room for each (its size and hash), PUT the
 *  bytes straight to the file store, then finish it. `onEach` counts the finished ones. */
export async function uploadFiles(folder: string, list: File[], onEach?: (n: number) => void): Promise<void> {
  const brain = selectedBrain();
  const big = list.find((f) => f.size > BROWSER_MAX_BYTES);
  if (big) throw new Error(`${big.name} is over 500 MB, the most the browser uploads.`);
  let finished = 0;
  for (let i = 0; i < list.length; i += 100) {
    const chunk = list.slice(i, i + 100);
    const items = [];
    for (const f of chunk) {
      // one at a time: each is read whole to hash it
      items.push({
        path: folder ? `${folder}/${f.name}` : f.name,
        size: f.size,
        sha256: await sha256Hex(f),
        content_type: f.type,
      });
    }
    const { files } = await send<{ files: Reserved[] }>('POST', '/files', { files: items }, brain);
    for (const [j, r] of files.entries()) {
      const res = await fetch(r.upload.url, { method: 'PUT', headers: r.upload.headers, body: chunk[j] }).catch(
        () => null,
      );
      if (!res?.ok) throw new Error(`Could not upload ${chunk[j].name}. Try again.`);
      await send('POST', `/files/${r.id}/done`, undefined, brain);
      onEach?.(++finished);
    }
  }
}

/** A file from the brain API, saved by the browser: the export, the curator skill, a file. */
export async function download(sub: string, filename: string): Promise<void> {
  const blob = await brainFetch<Blob>(`/brain${sub}`, {}, undefined, 'blob');
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface ImportReport {
  complete: boolean;
  processed: number;
  written: number;
  skipped: number;
  archived: number;
  counts: { pages: number; memories: number; files: number };
  path_changes: { from: string; to: string }[];
  removed: { path: string; counts: Removed[] }[];
  decoded: string[];
  oversized: string[];
  warnings: { path: string; reason: string }[];
  over_cap: string[];
  error: string | null;
  entries: { kind: string; path: string; planned: string; result: string }[];
}

export const importMarkdown = (file: File, dryRun: boolean, archiveMissing: boolean) =>
  brainFetch<ImportReport>(
    `/brain/import?dry_run=${dryRun}&archive_missing=${archiveMissing}&label=${encodeURIComponent(file.name)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/zip', 'X-Import-Name': encodeURIComponent(file.name) },
      body: file,
    },
  );

export interface BrainSettings {
  name: string;
  description: string;
  rules: string[];
  ai_access: 'read' | 'write' | 'inbox';
}
export interface Brain extends BrainSettings {
  id: number;
  folder: string;
  status: 'active' | 'archived';
  settled_at: string | null;
}
export interface BrainsView {
  brains: Brain[];
  caps: { brains: number; links: number; raisable: boolean };
  link_brains: number[];
}
export const getBrains = () => todoFetch<BrainsView>('/brains');
export const saveBrain = (fields: BrainSettings, id?: number) =>
  todoFetch<Brain>(id ? `/brains/${id}` : '/brains', { method: id ? 'PUT' : 'POST', body: JSON.stringify(fields) });
export const setBrainStatus = (id: number, status: 'archive' | 'restore') =>
  todoFetch<Brain>(`/brains/${id}/${status}`, { method: 'POST' });
export const setLinkBrains = (brains: number[]) =>
  todoFetch('/link-brains', { method: 'PUT', body: JSON.stringify({ brains }) });
export const moveToBrain = (
  kind: 'memory' | 'page',
  id: number,
  to_brain: number,
  expected_version: number,
  path?: string,
) => send('POST', '/move', { kind, id, to_brain, expected_version, ...(path === undefined ? {} : { path }) });
