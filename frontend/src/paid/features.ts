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

export function shortNameLabel() {
  return 'Short name (Pro or Max, no random code)';
}

export function brainLimitSentence(upsell: boolean | undefined) {
  return upsell ? 'More than one brain is part of Pro' : 'Your account has reached its brain limit.';
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
  return !!plan && !!(config?.billing || plan.manageable || granted(plan));
}
