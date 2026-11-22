import type { Session } from '../apps/todo-gtd/types';
import type { PaidConfig } from './types';

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
  if (upsell && allFree(session)) return 'Confirm your email in Settings to make more brains.';
  return upsell ? 'More than one brain is part of Pro' : 'Your account has reached its brain limit.';
}

/** Settings' email step: what confirming an email gives a hosted account. */
export function emailPerk(session: Session | null) {
  return allFree(session) ? 'Everything unlocked, free' : 'Higher limits, free';
}
