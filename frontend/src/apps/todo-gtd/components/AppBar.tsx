// The suite's app bar: a strip across the top of every app, once signed in. The apps
// that share the main address (FAMILY), this one and whatever else the account has
// turned on are tabs, this one marked; the rest of what this server has (config.apps)
// waits in a "More" menu. Another app opens through a hop (../hop.ts): a plain link,
// so it can open in a new tab too. On an app's old address (config.moved) the strip is
// a notice instead, with one button that carries this account over.
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { APP, APP_LINES, APP_SHORT, APP_TITLE, APP_TITLES, FAMILY } from '../../../core/app';
import { createSignInLink } from '../api';
import { hopHref, readHop, settleHop, useSuite } from '../hop';
import { useSession } from '../session';
import { APP_BORDER, Logo } from './Logo';

const TAB = 'flex shrink-0 items-center gap-1.5 border-b-2 -mb-px px-2.5 py-2 font-heading text-sm';

export function AppBar() {
  const config = useSuite();
  const session = useSession().session;
  const listId = session?.list_id ?? null;
  // A hop may need to come back here for a sign-in link, so the bar shows only where
  // this page's own app has an address (an anchor left to the request's has none).
  const keys = Object.keys(APP_SHORT).filter((k) => (config?.apps[k]?.url ?? '') !== '');
  if (!config || listId === null || !keys.includes(APP) || keys.length < 2) return null;
  if (config.moved) return <Moved to={config.moved} />;
  const on = session?.apps ?? [];
  const tabs = keys.filter((k) => FAMILY.includes(k) || k === APP || on.includes(k));
  const more = keys.filter((k) => !tabs.includes(k));

  return (
    <div className="flex w-full items-stretch bg-cream">
      <nav
        aria-label="Apps"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto border-b border-line-faint px-2 sm:px-4"
      >
        {tabs.map((key) => {
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
      {more.length > 0 && <MoreApps apps={more.map((key) => ({ key, href: hopHref(config.apps[key].url, listId) }))} />}
    </div>
  );
}

/** The apps this account has not turned on, one line each. It sits beside the
 *  strip, not in it: the strip scrolls sideways and would clip the open menu. */
function MoreApps({ apps }: { apps: { key: string; href: string }[] }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const panelId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    const onOutside = (e: Event) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onOutside);
    document.addEventListener('focusin', onOutside);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onOutside);
      document.removeEventListener('focusin', onOutside);
    };
  }, [open]);

  return (
    <div ref={wrap} className="relative flex shrink-0 border-b border-line-faint pr-2 sm:pr-4">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="px-2.5 py-2 font-heading text-sm text-muted hover:text-charcoal"
      >
        More<span aria-hidden="true"> ▾</span>
      </button>
      {open && (
        <div
          id={panelId}
          className="absolute right-2 top-full z-40 mt-1 w-72 max-w-[calc(100vw-1rem)] rounded-lg border border-line bg-cream p-1 shadow-lg sm:right-4"
        >
          {apps.map(({ key, href }) => (
            <a key={key} href={href} className="flex items-start gap-2.5 rounded-lg px-3 py-2 hover:bg-sand">
              <Logo app={key} className="mt-0.5 h-5 w-5 shrink-0" />
              <span>
                <span className="block font-heading text-sm font-semibold text-charcoal">{APP_TITLES[key]}</span>
                <span className="block text-xs text-muted">{APP_LINES[key]}</span>
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

/** On the app's old address: where it lives now, and one button that mints a
 *  sign-in link for this account there. No tabs: a hop from here could not find its
 *  way back, because every app's address is now the new one. */
function Moved({ to }: { to: string }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const go = async () => {
    setBusy(true);
    setFailed(false);
    try {
      window.location.replace((await createSignInLink(APP)).url);
      // Busy until the page has gone: a second press would mint a second link.
    } catch {
      setFailed(true);
      setBusy(false);
    }
  };
  return (
    <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line-faint bg-cream px-3 py-2 text-sm text-charcoal sm:px-4">
      <p>
        {APP_TITLE} now lives at <strong>{to.replace(/^https?:\/\//, '')}</strong>. This address keeps working, and so
        does the link your AI uses.
      </p>
      <button
        type="button"
        disabled={busy}
        onClick={() => void go()}
        className="rounded-lg border border-line bg-cream px-3 py-1.5 font-heading text-sm text-charcoal hover:bg-sand disabled:opacity-40"
      >
        {busy ? 'Opening…' : 'Take me there'}
      </button>
      {failed && (
        <span role="alert" className="text-brand-ink">
          Could not open it. Try again.
        </span>
      )}
    </div>
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
