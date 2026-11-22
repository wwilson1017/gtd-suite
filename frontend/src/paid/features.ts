import type { Session } from '../apps/todo-gtd/types';
import type { PaidConfig, Plan } from './types';

export const NO_PAID_OFFERS: PaidConfig = { billing: false };

export function offersPlans(config: PaidConfig | null) {
  return config?.billing;
}

export function mayLockPage(session: Session | null) {
  return session?.plan?.pro === true || session?.hosted === false;
}

/** The server sends counts only when the account may see them, including self-hosts. */
export function showsViews(site: { views?: number }) {
  return site.views !== undefined;
}

/** The suite is free (backend paid_settings.free_max): no plan is shown or sold. */
export function allFree(session: Session | null) {
  return session?.plan?.free === true;
}

export function shortNameLabel(session: Session | null) {
  return allFree(session) ? 'Short name (no random code)' : 'Short name (Pro or Max, no random code)';
}

export function brainLimitSentence(upsell: boolean | undefined, session: Session | null) {
  if (upsell && allFree(session)) return 'Confirm your email in Connect to make more brains.';
  return upsell ? 'More than one brain is part of Pro' : 'Your account has reached its brain limit.';
}

/** Settings' email step: what confirming an email gives a hosted account. */
export function emailPerk(session: Session | null) {
  return allFree(session) ? 'Everything unlocked, free' : 'Higher limits, free';
}

/** A plan from the operator's free grant (admin comp) rather than a live subscription:
 *  the server says which (plans.pro_source). */
export function granted(plan: Plan): boolean {
  return plan.source === 'comp' && !!plan.comp_until;
}

/** Whether the card has anything to show. A free grant needs no Stripe, so it shows even
 *  where sales are off. */
export function planShown(config: PaidConfig | null, session: Session | null): boolean {
  const plan = session?.plan;
  if (allFree(session)) return false;
  return !!plan && !!(config?.billing || plan.manageable || granted(plan));
}
