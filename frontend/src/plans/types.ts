/** The session's level block (backend plans/routes.session_plan). */
export interface Level {
  /** On a raised level (plans.active): granted, or stored by the extension. */
  raised: boolean;
  /** The level now (plans.of): the stored tier keys, or null. */
  tier?: 'pro' | 'max' | null;
  /** The suite is free (backend plans/settings.free_max): a confirmed hosted account has
   *  everything, and no level is shown. */
  free?: boolean;
}

export interface OffersConfig {
  /** The optional extension offers something here (backend plans/extension.offers()). */
  offers?: boolean;
  /** The suite is free: confirming an email unlocks everything (plans/settings.free_max). */
  free?: boolean;
}
