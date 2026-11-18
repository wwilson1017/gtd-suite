// Todo GTD — the sign-in page (/signin/{token}), reached from a sign-in email or a
// QR code made under Connect on a device that is already signed in.
//
// Loading this page changes NOTHING: mail scanners and link previews fetch links,
// and a GET that redeemed would spend the one-time link before its owner ever saw
// it. Only the button's POST redeems.
import { useState } from 'react';
import { ApiError } from '../../core/api/client';
import { BASE, APP, APP_TITLE } from '../../core/app';
import { redeemSignIn } from './api';
import { PageFrame } from './components/PageFrame';
import { useConfig } from './useConfig';

// Todo's own words; on another app's address (an app bar hop ends here the first
// time) the page names that app.
const WORDS =
  APP === 'todo'
    ? { title: 'Sign in to your list', button: 'Open my list on this device', what: 'list' }
    : { title: `Sign in to ${APP_TITLE}`, button: `Open ${APP_TITLE} on this device`, what: 'account' };

export function SignInPage({ token }: { token: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const config = useConfig();

  const redeem = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await redeemSignIn(token);
      window.location.replace(BASE + '/app'); // Back must not return to a spent link
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 404
          ? 'This sign-in link isn’t valid any more. It works once, for one hour — ask for a new one.'
          : 'Could not sign in right now — try again in a minute.',
      );
      setBusy(false);
    }
  };

  return (
    <PageFrame>
      <h1 className="font-heading text-2xl font-bold text-charcoal">{WORDS.title}</h1>
      <p className="mt-3 text-sm text-charcoal">
        This opens the {WORDS.what} on this device and keeps this browser signed in to it. Nothing else changes: every
        other device stays signed in.
      </p>
      {config?.signed_in && (
        <p className="mt-2 text-sm font-semibold text-charcoal">
          This browser is signed in to {WORDS.what === 'list' ? 'a list' : 'an account'} already. Continuing signs it
          out of that one here, in every tab.
        </p>
      )}
      <button
        type="button"
        onClick={() => void redeem()}
        disabled={busy}
        className="mt-5 rounded-lg bg-brand-dark px-5 py-2.5 font-heading text-white hover:bg-brand-deep disabled:opacity-40"
      >
        {busy ? 'Working…' : WORDS.button}
      </button>
      {error && (
        <p role="alert" className="mt-3 text-sm text-brand-ink">
          {error}
        </p>
      )}
      <p className="mt-6 text-sm">
        <a href={BASE + '/'} className="text-muted underline hover:text-charcoal">
          Home
        </a>
      </p>
    </PageFrame>
  );
}
