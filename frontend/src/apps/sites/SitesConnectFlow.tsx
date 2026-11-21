import { useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { SPRINGFORM_EMAIL, SPRINGFORM_OFFER } from '../../paid/springform';
import { createList, getConfig, requestSignIn, setEmail, todoFetch } from '../todo-gtd/api';
import { PageFrame } from '../todo-gtd/components/PageFrame';
import { bootstrap, pinnedListId, useSession } from '../todo-gtd/session';

export function SitesConnectFlow() {
  const query = new URLSearchParams(window.location.search);
  const code = query.get('code') ?? '';
  // The server refuses an approval whose client differs from the code's, so this wording is the truth.
  const springform = query.get('client') === 'springform';
  const where = springform ? 'Springform' : 'your terminal';
  const valid = /^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/.test(code);
  const { session } = useSession();
  const [ready, setReady] = useState(false);
  const [mail, setMail] = useState(false);
  const [canCreate, setCanCreate] = useState(false);
  const [hosted, setHosted] = useState(false);
  const [created, setCreated] = useState(false);
  const [email, setEmailInput] = useState('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    void getConfig()
      .then(async (config) => {
        if (config.signed_in) {
          await bootstrap();
          if (pinnedListId() === null) throw new Error('Session unavailable');
        }
        if (active) {
          setMail(config.mail);
          setHosted(config.open_signup);
          setCanCreate(config.open_signup || !config.claimed);
          setReady(true);
        }
      })
      .catch(() => {
        if (active) setError('Could not load this connection. Reload to try again.');
      });
    return () => {
      active = false;
    };
  }, []);

  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not connect. Try again.'));
    }
    setBusy(false);
  };

  const create = async () => {
    await createList(Intl.DateTimeFormat().resolvedOptions().timeZone, '', code);
    await bootstrap();
    if (pinnedListId() === null) throw new Error('Account created. Reload to finish connecting.');
    setCreated(true);
    if (email.trim()) await setEmail(email.trim());
  };
  const approve = async () => {
    await todoFetch(`/connect/${encodeURIComponent(code)}`, {
      method: 'POST',
      body: JSON.stringify({
        ...(created ? {} : { typed_code: typed.trim() }),
        ...(springform ? { client: 'springform' } : {}),
      }),
    });
    setApproved(true);
  };
  const input = 'mt-1 block w-full rounded-lg border border-line bg-cream px-3 py-2 text-charcoal';
  const button = 'mt-4 rounded-lg bg-brand-dark px-4 py-2 text-white disabled:opacity-40';

  return (
    <PageFrame>
      <h1 className="font-heading text-2xl font-bold text-charcoal">
        {springform ? 'Connect Springform to your GTD account' : 'Connect your AI to Simple Sites'}
      </h1>
      {!valid ? (
        <p role="alert">This connection code is invalid. Run connect again in {where}.</p>
      ) : (
        <>
          {/* Only the account this code just made sees it: anyone else must type it from their own terminal. */}
          {created && (
            <p className="mt-3 text-charcoal">
              Connection code: <strong>{code}</strong>
            </p>
          )}
          {approved ? (
            <p className="mt-4">
              Approved. Return to {where} to finish connecting. If it missed the answer, run connect again.
            </p>
          ) : ready ? (
            session ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(approve);
                }}
              >
                {springform ? (
                  <p className="mt-3">
                    {SPRINGFORM_OFFER} Approving gives it your account’s agent link and turns every app on.
                    {hosted && ' Your email must be confirmed first.'}
                  </p>
                ) : (
                  <p className="mt-3">
                    Approving gives this AI your account’s agent link and turns Simple Sites on. It can use the apps you
                    have enabled.
                  </p>
                )}
                {!created && (
                  <label className="mt-3 block">
                    Type the code shown in {where}. If you did not start this in your own{' '}
                    {springform ? 'Springform' : 'terminal'}, do not approve it.
                    <input
                      className={input}
                      value={typed}
                      onChange={(e) => setTyped(e.target.value)}
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </label>
                )}
                <button className={button} disabled={busy || (!created && !typed.trim())}>
                  Approve
                </button>
              </form>
            ) : (
              <div>
                <p className="mt-3">
                  Create an account or sign in, then approve this connection. The code expires after 15 minutes.
                </p>
                {mail && (
                  <label className="mt-3 block">
                    {springform && hosted ? SPRINGFORM_EMAIL : 'Email (optional for a new account)'}
                    <input
                      className={input}
                      type="email"
                      value={email}
                      onChange={(e) => setEmailInput(e.target.value)}
                    />
                  </label>
                )}
                {canCreate && (
                  <button
                    className={button}
                    // Springform's grant needs a confirmed email (connect.approve), so ask for one up front.
                    disabled={busy || (springform && hosted && (!mail || !email.trim()))}
                    onClick={() => void run(create)}
                  >
                    Create account
                  </button>
                )}
                {mail && (
                  <button
                    className={`${button} ml-2`}
                    disabled={busy || !email.trim()}
                    onClick={() =>
                      void run(async () => {
                        await requestSignIn(email.trim());
                        setSent(true);
                      })
                    }
                  >
                    Sign in
                  </button>
                )}
                {sent && (
                  <p className="mt-3">
                    Check your email and open the sign-in link. Then return here and{' '}
                    <a href={window.location.pathname + window.location.search} className="underline">
                      continue connecting
                    </a>
                    .
                  </p>
                )}
                {hosted && (
                  <p className="mt-3 text-sm">Your first site comes down after 7 days unless you confirm your email.</p>
                )}
              </div>
            )
          ) : (
            <p className="mt-3">Loading…</p>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="mt-3 text-brand-ink">
          {error}
        </p>
      )}
    </PageFrame>
  );
}
