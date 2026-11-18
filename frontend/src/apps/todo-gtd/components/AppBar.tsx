// The suite's app bar: a strip across the top of every app, once signed in, naming
// each app this server has (config.apps) with this one marked. Another app opens
// through a hop (../hop.ts): a plain link, so it can open in a new tab too.
import { useEffect, useState, type ReactNode } from 'react';
import { APP, APP_SHORT, APP_TITLES } from '../../../core/app';
import { hopHref, knownSuite, readHop, settleHop, suiteConfig } from '../hop';
import { useSession } from '../session';
import { APP_BORDER, Logo } from './Logo';

const TAB = 'flex shrink-0 items-center gap-1.5 border-b-2 -mb-px px-2.5 py-2 font-heading text-sm';

export function AppBar() {
  const [config, setConfig] = useState(knownSuite);
  const listId = useSession().session?.list_id ?? null;
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
  // A hop may need to come back here for a sign-in link, so the bar shows only where
  // this page's own app has an address (an anchor left to the request's has none).
  const keys = Object.keys(APP_SHORT).filter((k) => (config?.apps[k]?.url ?? '') !== '');
  if (!config || listId === null || !keys.includes(APP) || keys.length < 2) return null;

  return (
    <nav
      aria-label="Apps"
      className="flex w-full items-center gap-1 overflow-x-auto border-b border-line-faint bg-cream px-2 sm:px-4"
    >
      {keys.map((key) => {
        const label = (
          <>
            <Logo app={key} className="h-5 w-5" />
            {APP_SHORT[key]}
          </>
        );
        return key === APP ? (
          <span key={key} aria-current="page" className={`${TAB} ${APP_BORDER[key]} font-semibold text-charcoal`}>
            {label}
          </span>
        ) : (
          <a
            key={key}
            href={hopHref(config.apps[key].url, listId)}
            title={`Open ${APP_TITLES[key]}`}
            className={`${TAB} border-transparent text-muted hover:text-charcoal`}
          >
            {label}
          </a>
        );
      })}
    </nav>
  );
}

/** Signed out here, with a hop's mark (/app sent the browser to /): back to the app
 *  it came from for a sign-in link. Anything else gets `children`, the landing. */
export function HopBack({ children }: { children: ReactNode }) {
  const [hop] = useState(readHop);
  const [away, setAway] = useState(hop !== null && 'from' in hop);
  useEffect(() => {
    // Signed out, so no account can show: stuck falls back to the landing.
    if (hop && 'from' in hop) void settleHop(hop, null).then((s) => setAway(s === 'away'));
  }, [hop]);
  return away ? null : children;
}
