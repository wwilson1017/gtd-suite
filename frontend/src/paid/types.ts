export interface Plan {
  /** On Pro or better, paid or granted. */
  pro: boolean;
  /** The plan now (plans.of): Max is only granted, and outranks a subscription. */
  tier?: 'pro' | 'max' | null;
  /** The subscription's Stripe status ('' = never bought). */
  status: string;
  /** The end of its current period (ISO), or null. */
  until: string | null;
  /** It ends at `until` instead of renewing (cancelled in Manage billing). */
  cancels: boolean;
  /** Manage billing (Stripe's portal) can be opened for this account. */
  manageable: boolean;
  /** A free plan granted by the operator, until this instant (9999… = for good), or null. */
  comp_until?: string | null;
  /** Where the plan comes from now: a live subscription, the operator's grant, or neither. */
  source?: 'stripe' | 'comp' | null;
}

export interface PaidConfig {
  /** Pro can be bought here (backend/paid/billing.py selling()). */
  billing?: boolean;
}
