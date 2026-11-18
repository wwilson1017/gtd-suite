// Todo GTD — the "keep this list" banner under the shell's header. Shown on a
// hosted server while the list has no confirmed email and the server can mail one:
// until then the list lives only in this browser, with the small anonymous caps.
// Dismissing it is remembered per list on this device (dismissed.ts); a create
// refused at the cap (session.ts `capped`) brings it back, urgent.
import { Link } from 'react-router-dom';
import { useDismissed } from './dismissed';
import { todoPath } from './publicMode';
import { setCapped, useSession } from './session';

export function KeepBanner() {
  const { session, capped } = useSession();
  const [dismissed, setDismissed] = useDismissed('keep-banner', session?.list_id);
  if (!session?.hosted || session.verified || !session.mail) return null;
  if (dismissed && !capped) return null;

  const dismiss = () => {
    setDismissed();
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
          Add your email in Settings
        </Link>{' '}
        to keep it, use it on other devices and raise its limits.
      </p>
      <button type="button" onClick={dismiss} aria-label="Dismiss" className="shrink-0 text-muted hover:text-charcoal">
        ✕
      </button>
    </div>
  );
}
