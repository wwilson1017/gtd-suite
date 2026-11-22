import type { Session } from '../apps/todo-gtd/types';
import type { OffersConfig } from './types';

export const NO_OFFERS: OffersConfig = { offers: false };

export function offers(config: OffersConfig | null) {
  return config?.offers;
}

export function mayLockPage(session: Session | null) {
  return session?.plan?.raised === true || session?.hosted === false;
}

/** The server sends counts only when the account may see them, including self-hosts. */
export function showsViews(site: { views?: number }) {
  return site.views !== undefined;
}

/** The suite is free (backend plans/settings.free_max): no level is shown. */
export function allFree(session: Session | null) {
  return session?.plan?.free === true;
}

export function shortNameLabel() {
  return 'Short name (no random code)';
}

export function brainLimitSentence(raisable: boolean | undefined, session: Session | null) {
  if (raisable && allFree(session)) return 'Confirm your email in Settings to make more brains.';
  return 'Your account has reached its brain limit.';
}

/** Settings' email step: what confirming an email gives a hosted account. */
export function emailPerk(session: Session | null) {
  return allFree(session) ? 'Everything unlocked, free' : 'Higher limits, free';
}
