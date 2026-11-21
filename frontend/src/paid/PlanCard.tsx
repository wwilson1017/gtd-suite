// Pro, the paid plan (backend/paid/billing.py): one plan for the whole account, sold and
// managed by Stripe. Shown where Pro can be bought (config.billing) or managed
// (plan.manageable, so a customer can always reach their billing). It lists only
// what Pro gives today; each later feature adds its line.
// simplification: the price is text here and in billing.PRICE; change both with Stripe's.
import { useEffect, useState } from 'react';
import { apiErrorMessage } from '../core/api/client';
import { manageBilling, startCheckout, syncBilling } from './api';
import { useSession } from '../apps/todo-gtd/session';
import { PolicyLinks } from './PolicyLinks';
import { granted, planShown } from './features';
import { useConfig } from '../apps/todo-gtd/useConfig';

const GIVES = [
  '10,000 memories and 25,000 pages in Common Brain',
  '2,500 pages and 2,500 short links on Simple Sites',
  'How many times each page was opened and each link followed',
  'Password-protected pages',
  'Bigger limits in Todo, Notes and Projects',
];

const primaryBtn =
  'rounded-lg bg-brand-dark px-4 py-2 font-heading text-sm text-white hover:bg-brand-deep disabled:opacity-40';
const secondaryBtn =
  'rounded-lg border border-line bg-cream px-4 py-2 font-heading text-sm text-charcoal hover:bg-sand disabled:opacity-40';

function day(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' }) : '';
}

/** Back from Checkout (?pro=welcome): ask the server to re-read the plan from Stripe
 *  (the webhook may be slow, or may never come), every 3 s for up to 30 s, then
 *  reload into the new limits. */
function useWelcome(pro: boolean): boolean {
  const [welcome] = useState(() => new URLSearchParams(window.location.search).get('pro') === 'welcome');
  useEffect(() => {
    if (!welcome) return;
    const done = () => window.location.replace(window.location.pathname);
    if (pro) {
      done();
      return;
    }
    let tries = 0;
    const check = () => {
      tries += 1;
      syncBilling().then(
        (p) => {
          if (p.pro || tries >= 10) done();
        },
        () => {
          if (tries >= 10) done();
        },
      );
    };
    check();
    const timer = window.setInterval(check, 3000);
    return () => window.clearInterval(timer);
  }, [welcome, pro]);
  return welcome;
}

export function PlanCard() {
  const config = useConfig();
  const session = useSession().session;
  const plan = session?.plan;
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const welcome = useWelcome(plan?.pro === true);
  if (!session || !plan || !planShown(config, session)) return null;

  const go = async (what: string, ask: () => Promise<{ url: string }>) => {
    setBusy(what);
    setError('');
    try {
      window.location.assign((await ask()).url);
      // Held until the page has gone: a second press would open a second checkout.
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not reach the payment service. Try again.'));
      setBusy('');
    }
  };
  const manage = plan.manageable && (
    <button
      type="button"
      disabled={busy !== ''}
      onClick={() => void go('manage', manageBilling)}
      className={secondaryBtn}
    >
      {busy === 'manage' ? 'Opening…' : 'Manage billing'}
    </button>
  );

  return (
    <section className="rounded-xl border border-line-faint bg-cream p-4">
      {welcome && !plan.pro ? (
        <p role="status" className="text-sm text-charcoal">
          Payment received. Pro turns on in a moment…
        </p>
      ) : !plan.pro && ['past_due', 'unpaid', 'incomplete', 'paused'].includes(plan.status) ? (
        <>
          <h2 className="font-heading text-sm font-bold text-charcoal">Pro is paused</h2>
          <p className="mt-1 text-sm text-charcoal">
            The last payment didn't go through. Pay or cancel in Manage billing; Pro comes back as soon as it is paid.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">{manage}</div>
        </>
      ) : plan.pro ? (
        <>
          <h2 className="font-heading text-sm font-bold text-charcoal">
            You're on {plan.tier === 'max' ? 'Max' : 'Pro'}
          </h2>
          <p className="mt-1 text-sm text-charcoal">
            {granted(plan)
              ? plan.comp_until!.startsWith('9999')
                ? 'Free, on the house.'
                : `Free until ${day(plan.comp_until!)}.`
              : plan.status === 'past_due'
                ? 'Your card needs attention: update it in Manage billing to keep Pro.'
                : plan.cancels
                  ? `Pro until ${day(plan.until)}, then free. Everything you made stays.`
                  : `Renews ${day(plan.until)}.`}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">{manage}</div>
        </>
      ) : config?.billing ? (
        <>
          <h2 className="font-heading text-sm font-bold text-charcoal">Go Pro</h2>
          <ul className="mt-1 list-disc pl-5 text-sm text-charcoal">
            {GIVES.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
          {!session.verified && (
            <p className="mt-2 text-sm text-muted">Confirm your email first: Pro's receipts go there.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy !== '' || !session.verified}
              onClick={() => void go('year', () => startCheckout('year'))}
              className={primaryBtn}
            >
              {busy === 'year' ? 'Opening…' : '$36 a year (save 40%)'}
            </button>
            <button
              type="button"
              disabled={busy !== '' || !session.verified}
              onClick={() => void go('month', () => startCheckout('month'))}
              className={secondaryBtn}
            >
              {busy === 'month' ? 'Opening…' : '$5 a month'}
            </button>
            {manage}
          </div>
          <p className="mt-2 text-xs text-muted">
            One plan for your whole account. Cancel any time; nothing you made is removed. Sold through Link, Stripe's
            merchant of record.
          </p>
          <PolicyLinks className="mt-1 text-xs text-muted" />
        </>
      ) : (
        <>
          <h2 className="font-heading text-sm font-bold text-charcoal">Billing</h2>
          <div className="mt-2 flex flex-wrap gap-2">{manage}</div>
        </>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </section>
  );
}
