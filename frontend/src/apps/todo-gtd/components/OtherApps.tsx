// The suite's apps (backend/apps.py), for Settings › Your apps: the same account, and the same
// agent link, in each. A switch turns an app on or off for the account: the agent
// link offers only the apps that are on, and an app that is off shows AppOff on its
// own address; nothing in it is removed. Opening another app mints a one-hour
// sign-in link on its own address (cookies are per address) and goes there; its
// page asks for one button press, which also turns that app on.
import { useState } from 'react';
import { apiErrorMessage } from '../../../core/api/client';
import { APP_TITLES } from '../../../core/app';
import { createSignInLink, setApp } from '../api';
import { updateSession, useSession } from '../session';
import { hasOtherApps, useConfig } from '../useConfig';

/** `titled`: with its own heading (Common Brain's Connect page); Settings heads it already. */
export function OtherApps({ titled = true }: { titled?: boolean }) {
  const config = useConfig();
  const on = useSession().session?.apps ?? [];
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  // config.apps lists the apps with an address. This page's own app is served even
  // without one (the anchor falls back to the request's address), so it is listed too.
  const listed = config?.apps ?? {};
  const apps =
    config && !(config.app in listed)
      ? [[config.app, { title: APP_TITLES[config.app] ?? config.app, url: '' }] as const, ...Object.entries(listed)]
      : Object.entries(listed);
  if (!hasOtherApps(config)) return null;

  const toggle = async (key: string, next: boolean) => {
    setBusy(`toggle:${key}`);
    setError('');
    try {
      updateSession(await setApp(key, next));
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not change it — try again.'));
    }
    setBusy('');
  };
  const open = async (key: string) => {
    setBusy(`open:${key}`);
    setError('');
    try {
      window.location.assign((await createSignInLink(key)).url);
      // Busy until the page has gone: a second press would mint a second link.
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not open it — try again.'));
      setBusy('');
    }
  };

  return (
    <section className="rounded-xl border border-line-faint bg-cream p-4">
      {titled && <h2 className="mb-1 font-heading text-sm font-bold text-charcoal">Your apps</h2>}
      <p className="text-xs text-muted">
        {titled && 'One account, and one agent link, for all of them. '}The agent link offers the apps that are on.
        Opening one signs this browser in there and turns it on.
      </p>
      <ul className="mt-2 space-y-2">
        {apps.map(([key, app]) => (
          <li key={key} className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm text-charcoal">
              <input
                type="checkbox"
                checked={on.includes(key)}
                disabled={busy !== ''}
                onChange={(e) => void toggle(key, e.target.checked)}
                className="h-4 w-4 accent-brand-dark"
              />
              {app.title} {on.includes(key) ? 'is on' : 'is off'}
            </label>
            {key !== config?.app && (
              <button
                type="button"
                disabled={busy !== ''}
                onClick={() => void open(key)}
                className="ml-auto rounded-lg border border-line bg-cream px-3 py-1.5 text-sm font-heading text-charcoal hover:bg-sand disabled:opacity-40"
              >
                {busy === `open:${key}` ? 'Opening…' : `Open ${app.title} →`}
              </button>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </section>
  );
}
