import { BASE } from '../../core/app';
// Todo GTD — what a put-away list shows instead of the app (the server's
// lifecycle.py). A hosted list with no confirmed email is put away after 60 days
// without use and put away for good after 180; nothing is ever erased. Archived:
// one button brings it back. Removed: confirming an email does, and keeps it for
// good. Either way the person can sign out and start a new list instead of being
// stuck here: "/" sends a signed-in browser back to /app, and creating a list is
// refused while signed in.
import { useState } from 'react';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { restoreList, signOut } from './api';
import { PageFrame } from './components/PageFrame';
import { EmailSection } from './ConnectPage';
import { useSession } from './session';

const btnCls =
  'rounded-lg border border-line bg-cream px-3 py-2 text-sm font-heading text-charcoal hover:bg-sand disabled:opacity-40';

const SIGN_OUT_WARNING =
  'Sign out and start a new list?\n\nThis list stays put away and comes ' +
  'back the same way later, from a browser signed in to it. It has no confirmed email, so ' +
  'unless another device is still signed in to it, there is no way back in after signing out.';

export function PutAwayPage() {
  const removed = useSession().session?.state === 'removed';
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const run = async (action: () => Promise<void>, failed: string) => {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      // A 403 means the list's state changed under us (archived → removed); the
      // session store has already switched pages, so there is nothing to say here.
      if (!(e instanceof ApiError && e.status === 403)) setError(apiErrorMessage(e, failed));
      setBusy(false);
    }
  };

  const bringBack = () =>
    run(async () => {
      await restoreList();
      window.location.reload();
    }, 'Could not bring the list back — try again.');

  const startOver = () => {
    if (!window.confirm(SIGN_OUT_WARNING)) return;
    void run(async () => {
      await signOut();
      window.location.replace(BASE + '/');
    }, 'Could not sign out — try again.');
  };

  return (
    <PageFrame>
      <h1 className="font-heading text-2xl font-bold text-charcoal">
        {removed ? 'This list is put away for good' : 'This list is put away'}
      </h1>
      {removed ? (
        <>
          <p className="mt-2 text-charcoal">
            Put away for good after 180 days without use. Nothing was deleted. Add your email and confirm it to bring
            the list back &mdash; it then stays for good. Your agent and capture links are off until then.
          </p>
          <div className="mt-4">
            <EmailSection />
          </div>
        </>
      ) : (
        <>
          <p className="mt-2 text-charcoal">Your list was put away after 60 days without use. Nothing was removed.</p>
          <button
            type="button"
            onClick={() => void bringBack()}
            disabled={busy}
            className="mt-5 rounded-lg bg-brand-dark px-5 py-2.5 font-heading text-white hover:bg-brand-deep disabled:opacity-40"
          >
            Bring it back
          </button>
        </>
      )}
      <div className="mt-8 border-t border-line-faint pt-4">
        <button type="button" onClick={startOver} disabled={busy} className={btnCls}>
          Sign out and start a new list
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </PageFrame>
  );
}
