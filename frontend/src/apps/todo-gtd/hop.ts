// Going from one app of the suite to another on the same account (AppBar). Cookies
// are per address, so a hop is a plain link to the other app's /app carrying
// #from=<this app>.<list id>; a fragment never reaches a server.
// - Signed in there to the same list: SessionGate drops the mark, and that is all.
// - Signed out there (/app answers 303 /, and the browser keeps the fragment), or
//   signed in to another list: the page sends the browser back to the app it came
//   from with #to=<this app>, which mints a one-hour sign-in link for it and goes
//   there. That page asks for one press, as every sign-in link does: no hop signs a
//   browser in by itself.
// Every address comes from the server's own list (config.apps), never from the URL.
import { useEffect, useState } from 'react';
import { APP } from '../../core/app';
import { createSignInLink, getConfig, type AppConfig } from './api';
import { useSession } from './session';

let asked: Promise<AppConfig> | null = null;
let known: AppConfig | null = null;

/** The server's config, asked once per page load: the app bar is on every page. */
export function suiteConfig(): Promise<AppConfig> {
  // Asked inside a then, so even a throw before the request is a rejection.
  asked ??= Promise.resolve()
    .then(() => getConfig())
    .then(
      (c) => (known = { ...c, apps: c.apps ?? {} }),
      (e: unknown) => {
        asked = null;
        throw e;
      },
    );
  return asked;
}

/** The config if it has arrived, so a page that mounts later draws the bar at once. */
export function knownSuite(): AppConfig | null {
  return known;
}

/** The config for a component: null until it has arrived (and if it cannot be read). */
export function useSuite(): AppConfig | null {
  const [config, setConfig] = useState(knownSuite);
  useEffect(() => {
    let live = true;
    suiteConfig().then(
      (c) => {
        if (live) setConfig(c);
      },
      () => {},
    );
    return () => {
      live = false;
    };
  }, []);
  return config;
}

export function hopHref(url: string, listId: number): string {
  return `${url}/app#from=${APP}.${listId}`;
}

/** A link that opens another app on this account, or null where there is none to
 *  offer: the app has no address on this server, or this page is on an app's old
 *  address (config.moved), which a hop could not come back to. */
export function useAppHref(app: string): string | null {
  const config = useSuite();
  const listId = useSession().session?.list_id ?? null;
  const url = config?.apps[app]?.url;
  return !config || config.moved || !url || listId === null ? null : hopHref(url, listId);
}

export type Hop = { from: string; list: number } | { to: string };

export function readHop(hash = window.location.hash): Hop | null {
  const from = /^#from=([a-z]+)\.(\d+)$/.exec(hash);
  if (from) return { from: from[1], list: Number(from[2]) };
  const to = /^#to=([a-z]+)$/.exec(hash);
  return to ? { to: to[1] } : null;
}

/** What a hop came to: `stay` on this page (the mark is gone), `away` to another
 *  address, or `stuck`: it landed on another account (or none) and the way back
 *  could not be found, so nothing of this account may show; the mark stays, so a
 *  reload tries again. */
export type Settled = 'stay' | 'away' | 'stuck';

/** Carry a hop on (`listId` is this browser's list here, null when signed out). */
export async function settleHop(hop: Hop, listId: number | null): Promise<Settled> {
  const drop = () => history.replaceState(history.state, '', window.location.pathname + window.location.search);
  if ('to' in hop) {
    drop();
    if (listId === null || hop.to === APP) return 'stay';
    try {
      window.location.replace((await createSignInLink(hop.to)).url);
      return 'away';
    } catch {
      return 'stay'; // this browser's own account, here: nothing wrong is shown
    }
  }
  if (hop.list === listId) {
    drop();
    return 'stay';
  }
  let back: string | undefined;
  try {
    back = (await suiteConfig()).apps[hop.from]?.url;
  } catch {
    return 'stuck';
  }
  if (!back || hop.from === APP) {
    drop(); // not a hop this suite made: this browser's own session here is right
    return 'stay';
  }
  window.location.replace(`${back}/app#to=${APP}`);
  return 'away';
}
