// Settings › Security, in every app: the account's Enhanced security switch
// (backend lists.set_enhanced_security), with what it does and what it does not.
// Only the person changes it, here: no AI tool can.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../../core/api/client';
import { todoFetch } from '../api';
import { updateSession, useSession } from '../session';
import type { Session } from '../types';
import { SETTINGS } from './setup';

export function SecuritySection() {
  const { session } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const toggle = async (on: boolean) => {
    setBusy(true);
    setError('');
    try {
      updateSession(
        await todoFetch<Pick<Session, 'enhanced_security' | 'agent_link_expired'>>('/security', {
          method: 'PUT',
          body: JSON.stringify({ on }),
        }),
      );
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not change Enhanced security. Try again.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line-faint bg-cream p-4 text-sm text-charcoal sm:p-5">
        <label className="font-heading text-base font-bold">
          <input
            type="checkbox"
            checked={session?.enhanced_security ?? false}
            disabled={busy || !session}
            onChange={(e) => void toggle(e.target.checked)}
          />{' '}
          Enhanced security
        </label>
        {error && (
          <p role="alert" className="mt-2">
            {error}
          </p>
        )}
        <p className="mt-3 text-muted">While it is on:</p>
        <ul className="mt-1 list-disc space-y-1.5 pl-5">
          <li>
            Your agent link stops working after 30 days without use. A new link, made under{' '}
            <Link to={`${SETTINGS}/ai`} className="underline">
              Connect your AI
            </Link>
            , starts again.
          </li>
          <li>
            A new program key or staff link needs an end date: 30, 90 or 365 days. The ones you already have keep
            working, with no end date.
          </li>
          <li>You get an email when a new AI tool first uses your agent link, once a day at most.</li>
        </ul>
        {session && !session.mail ? (
          <p className="mt-3 text-muted">This server cannot send email, so it sends no alerts.</p>
        ) : (
          session &&
          !session.verified && (
            <p className="mt-3">
              <Link to={`${SETTINGS}/email`} className="font-semibold underline">
                Add your email
              </Link>{' '}
              to get the alerts: they go only to a confirmed address.
            </p>
          )
        )}
        <p className="mt-3 text-muted">
          What the email cannot catch: a tool is known by the name it gives, so one that copies the name of a tool you
          already use raises no email, and after 50 names nothing new is recorded or emailed.
        </p>
        <p className="mt-3 text-muted">
          Turning it off: an agent link that stopped for lack of use works again, and end dates already on keys and
          links still hold.
        </p>
      </section>
    </div>
  );
}
