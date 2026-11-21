// Todo GTD — "this list is full", under the shell's header: shown on a hosted server
// when a create was refused at the anonymous cap (session.ts `capped`) while the list has
// no confirmed email and the server can mail one. Confirming an email raises the caps.
// Until then the next-step button in the header keeps "Add your email" one tap away.
import { Link } from 'react-router-dom';
import { SETTINGS } from './settings/setup';
import { setCapped, useSession } from './session';

export function KeepBanner() {
  const { session, capped } = useSession();
  if (!capped || !session?.hosted || session.verified || !session.mail) return null;

  return (
    <div
      role="alert"
      className="mt-4 flex items-start gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-charcoal dark:border-red-800 dark:bg-red-950/30"
    >
      <p className="min-w-0 flex-1">
        <strong>This list is full for now. </strong>
        <Link to={`${SETTINGS}/email`} className="font-semibold underline">
          Add your email
        </Link>{' '}
        to keep it, use it on other devices and raise its limits.
      </p>
      <button
        type="button"
        onClick={() => setCapped(false)}
        aria-label="Dismiss"
        className="shrink-0 text-muted hover:text-charcoal"
      >
        ✕
      </button>
    </div>
  );
}
