import { todoFetch } from '../apps/todo-gtd/api';

/** Upgrade: a Stripe Checkout address for Pro, billed by the month or the year. */
export function startCheckout(interval: 'month' | 'year'): Promise<{ url: string }> {
  return todoFetch<{ url: string }>('/billing/checkout', {
    method: 'POST',
    body: JSON.stringify({ interval }),
  });
}

/** Back from Checkout: have the server re-read the plan from Stripe now. */
export function syncBilling(): Promise<{ pro: boolean; status: string }> {
  return todoFetch<{ pro: boolean; status: string }>('/billing/sync', { method: 'POST' });
}

/** Manage billing: a Stripe Customer Portal address. */
export function manageBilling(): Promise<{ url: string }> {
  return todoFetch<{ url: string }>('/billing/manage', { method: 'POST' });
}
