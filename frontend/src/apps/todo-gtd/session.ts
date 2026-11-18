import { BASE } from '../../core/app';
// Todo GTD — which list this browser is signed in to (module pub/sub, the
// toast.ts pattern).
//
// The app's first call is GET /api/app/session (bootstrap): it names the list,
// and every other /api/app request carries that id as X-List (api.ts). Every tab
// shares the cookie, so a sign-in completed in another tab changes the list the
// cookie names; this tab's next request then gets 409 {list_changed} and the page
// reloads into whatever list the browser is in now, instead of writing into the
// wrong one. A 401 means signed out (→ the home page); a 403 {state} means the
// list is put away (→ PutAwayPage, for that state). A 400 that says the list is at
// its anonymous cap sets `capped`, which brings back the "keep this list" banner
// (KeepBanner).
//
// # simplification: no cross-tab broadcast — a stale tab finds out on its next request
import { useSyncExternalStore } from 'react';
import { ApiError } from '../../core/api/client';
import { initializeBrains } from './brainSelection';
import { getSession } from './api';
import type { Session } from './types';

export type SessionKind = 'loading' | 'ok' | 'signedOut' | 'putAway' | 'listChanged' | 'error';

export interface SessionState {
  kind: SessionKind;
  /** The bootstrap answer; null until it has arrived. */
  session: Session | null;
  /** A create was refused because the list is at its anonymous cap. */
  capped: boolean;
}

const INITIAL: SessionState = { kind: 'loading', session: null, capped: false };
let current = INITIAL;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function set(next: SessionState) {
  current = next;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useSession(): SessionState {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  );
}

/** The list this tab is pinned to — what api.ts sends as X-List. */
export function pinnedListId(): number | null {
  return current.session?.list_id ?? null;
}

/** Ask the server which list this browser is in. Once per page load. */
export function bootstrap(): Promise<void> {
  inflight ??= getSession().then(
    (session) => {
      initializeBrains(session.list_id, session.brains ?? []);
      set({ ...current, kind: session.state === 'active' ? 'ok' : 'putAway', session });
    },
    (e: unknown) => {
      // A 401 has already sent the page home (api.ts → signedOut).
      if (!(e instanceof ApiError && e.status === 401)) set({ ...current, kind: 'error' });
    },
  );
  return inflight;
}

/** Fold a change this tab made (the email) into the pinned session. */
export function updateSession(patch: Partial<Session>) {
  if (current.session) set({ ...current, session: { ...current.session, ...patch } });
}

/** The cookie names no live session: go home. replace(), so Back does not return
 *  to a page that could only bounce again. */
export function signedOut() {
  set({ ...current, kind: 'signedOut' });
  window.location.replace(BASE + '/');
}

/** Set by api.ts on a cap refusal; cleared when the banner is dismissed. */
export function setCapped(capped: boolean) {
  if (current.capped !== capped) set({ ...current, capped });
}

/** The list was put away while this tab had it open (403 {state}). */
export function putAway(state: Session['state']) {
  set({ ...current, kind: 'putAway', session: current.session && { ...current.session, state } });
}

/** The browser is signed in to another list now: start over as that list. */
export function listChanged() {
  set({ ...current, kind: 'listChanged' });
  window.location.reload();
}

/** Forget the session (tests: this is module state, like the toasts). */
export function resetSession() {
  inflight = null;
  set(INITIAL);
}
