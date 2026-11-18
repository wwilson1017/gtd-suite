// Simple Sites — the pages-and-links API (backend/site_routes.py), through the todo
// app's fetch, which names the session's list (X-List) and handles signed-out,
// put-away and list-changed answers the same way for every app.
import { todoFetch } from '../todo-gtd/api';
import type { Site, SiteCaps, SiteFolder, SiteRecords } from './types';

function send<T>(method: string, sub: string, body?: unknown): Promise<T> {
  return todoFetch<T>(sub, { method, body: body === undefined ? undefined : JSON.stringify(body) });
}

export function listSites(): Promise<{ sites: Site[]; caps: SiteCaps; folders?: SiteFolder[] }> {
  return todoFetch<{ sites: Site[]; caps: SiteCaps; folders?: SiteFolder[] }>('/sites');
}

type Filing = { note?: string; folder?: string };

export function createPage(
  page: { content: string; format: 'markdown' | 'html'; name?: string } & Filing,
): Promise<Site> {
  return send('POST', '/sites', page);
}

export function createLink(link: { url: string; name?: string; short_name?: string } & Filing): Promise<Site> {
  return send('POST', '/sites/links', link);
}

export function updateSite(
  id: number,
  fields: { status?: Site['status']; title?: string; password?: string; data?: Site['data'] } & Filing,
): Promise<Site> {
  return send('PUT', `/sites/${id}`, fields);
}

/** Gone for good: the one delete in the suite, and only here, never from an agent. */
export function deleteSite(id: number): Promise<void> {
  return send('DELETE', `/sites/${id}`).then(() => undefined);
}

export function readSiteData(id: number, before?: number): Promise<SiteRecords> {
  return todoFetch(`/sites/${id}/data?limit=200${before === undefined ? '' : `&before=${before}`}`);
}

export function clearSiteData(id: number): Promise<void> {
  return send('DELETE', `/sites/${id}/data`).then(() => undefined);
}

// A one-use link the browser downloads itself, streaming to disk: a Blob would hold a
// whole site (up to 1 GB) in the tab's memory first.
export async function downloadZip(id: number): Promise<void> {
  const { url } = await send<{ url: string }>('POST', `/sites/${id}/zip-link`);
  const a = Object.assign(document.createElement('a'), { href: url, download: `site-${id}.zip` });
  a.click();
}
