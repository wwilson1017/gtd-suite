// Todo GTD — the "keep this list" banner under the shell's header. Shown on a
// hosted server while the list has no confirmed email and the server can mail one:
// until then the list lives only in this browser, with the small anonymous caps.
// Dismissing it is remembered per list on this device; a create refused at the
// cap (session.ts `capped`) brings it back, urgent.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { todoPath } from './publicMode';
import { setCapped, useSession } from './session';

const dismissedKey = (listId: number) => `todo-gtd-keep-banner-dismissed-${listId}`;

function wasDismissed(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false; // storage blocked: show it
  }
}

export function KeepBanner() {
  const { session, capped } = useSession();
  const key = session ? dismissedKey(session.list_id) : '';
  const [dismissed, setDismissed] = useState(() => key !== '' && wasDismissed(key));
  if (!session?.hosted || session.verified || !session.mail) return null;
  if (dismissed && !capped) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(key, '1');
    } catch {
      // storage blocked: dismissed until the next page
    }
    setDismissed(true);
    setCapped(false);
  };

  return (
    <div
      role={capped ? 'alert' : 'status'}
      className={`mt-4 flex items-start gap-3 rounded-xl border px-4 py-3 text-sm text-charcoal ${
        capped ? 'border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/30' : 'border-line-faint bg-cream'
      }`}
    >
      <p className="min-w-0 flex-1">
        {capped && <strong>This list is full for now. </strong>}
        This list lives in this browser.{' '}
        <Link to={todoPath('/connect#email')} className="font-semibold underline">
          Add your email under Connect
        </Link>{' '}
        to keep it, use it on other devices and raise its limits.
      </p>
      <button type="button" onClick={dismiss} aria-label="Dismiss" className="shrink-0 text-muted hover:text-charcoal">
        ✕
      </button>
    </div>
  );
}
