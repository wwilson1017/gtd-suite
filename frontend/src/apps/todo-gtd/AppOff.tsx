// What an app's own address shows when the account has that app turned off (Apps,
// under Connect): one button turns it back on. Nothing in it was removed, the other
// apps stay a tap away (the app bar, whose tab led here, is on top), and this device
// can still sign out, so turning every app off strands no one. The rest of Connect (the agent link, email) comes back with
// the app.
import { useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { APP, APP_TITLE } from '../../core/app';
import { setApp } from './api';
import { AppBar } from './components/AppBar';
import { OtherApps } from './components/OtherApps';
import { PageFrame } from './components/PageFrame';
import { ThisDevice } from './ConnectPage';
import { updateSession } from './session';

export function AppOff() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const turnOn = async () => {
    setBusy(true);
    setError('');
    try {
      updateSession(await setApp(APP, true));
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not turn it on — try again.'));
      setBusy(false);
    }
  };

  return (
    <>
      <AppBar />
      <PageFrame>
        <h1 className="font-heading text-2xl font-bold text-charcoal">{APP_TITLE} is off</h1>
        <p className="mt-2 text-charcoal">
          It is turned off for your account, so your agent link leaves it out. Nothing in it was removed.
        </p>
        <button
          type="button"
          onClick={() => void turnOn()}
          disabled={busy}
          className="mt-5 rounded-lg bg-brand-dark px-5 py-2.5 font-heading text-white hover:bg-brand-deep disabled:opacity-40"
        >
          Turn on {APP_TITLE}
        </button>
        {error && (
          <p role="alert" className="mt-2 text-sm text-brand-ink">
            {error}
          </p>
        )}
        <div className="mt-8 space-y-4">
          <OtherApps />
          <ThisDevice />
        </div>
      </PageFrame>
    </>
  );
}
