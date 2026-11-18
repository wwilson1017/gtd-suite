import { BASE } from '../../core/app';
/**
 * Todo GTD — where the web app lives.
 *
 * Every list's app is at the same fixed path, /app; which list it shows is decided
 * by the browser's session cookie (backend/sessions.py), never by the address. The
 * app talks to /api/app via raw fetch (api.ts).
 */

function detectBase(): string | null {
  // The base is a property of the URL the browser is on, so outside a browser
  // there is no such thing. The guard is load-bearing, not defensive: this module is
  // read at IMPORT time, and it is imported by modules that several suites exercise
  // in vitest's plain Node environment, where a bare `window` is a ReferenceError.
  if (typeof window === 'undefined') return null;
  const path = window.location.pathname.slice(BASE.length);
  return path === '/app' || path.startsWith('/app/') ? BASE + '/app' : null;
}

/** Router basename when the browser is on the web app, else null. */
export const TODO_PUBLIC_BASE = detectBase();

export const isTodoPublicMode = TODO_PUBLIC_BASE !== null;

/** The web app's API prefix. */
export const TODO_API_BASE = `${BASE}/api/app`;

/**
 * Route path for a todo page. The router basename already points at the app's
 * root, so the pages hang off '/': todoPath('/inbox') → '/inbox', todoPath() → '/'.
 */
export function todoPath(sub = ''): string {
  return sub || '/';
}
