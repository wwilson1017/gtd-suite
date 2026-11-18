// @vitest-environment jsdom
//
// Pro's card: hidden where Pro is neither sold nor managed; on a free account it
// offers the yearly and monthly plans (held until the email is confirmed); on Pro
// it says when it renews or ends, or that the card needs attention; Manage billing
// stays reachable for a customer after sales stop.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { Session } from '../apps/todo-gtd/types';
import type { Plan } from './types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(),
  startCheckout: vi.fn(),
  manageBilling: vi.fn(),
  syncBilling: vi.fn(),
}));
vi.mock('../apps/todo-gtd/api', () => api);
vi.mock('./api', () => api);

import { bootstrap, resetSession } from '../apps/todo-gtd/session';
import { PlanCard } from './PlanCard';

const FREE: Plan = { pro: false, status: '', until: null, cancels: false, manageable: false };
const SESSION: Session = {
  list_id: 7,
  state: 'active',
  email: 'pat@example.com',
  verified: true,
  hosted: true,
  mail: true,
  caps: { todos: 5000, projects: 1000, areas: 100 },
  apps: ['sites'],
  plan: FREE,
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const assign = vi.fn();
const replace = vi.fn();

async function show(plan: Partial<Plan>, { billing = true, verified = true } = {}) {
  api.getConfig.mockResolvedValue({ billing });
  api.getSession.mockResolvedValue({ ...SESSION, verified, plan: { ...FREE, ...plan } });
  resetSession();
  await act(async () => {
    await bootstrap();
  });
  await act(async () => {
    root.render(<PlanCard />);
  });
}
const button = (label: string) =>
  [...host.querySelectorAll('button')].find((b) => b.textContent === label) as HTMLButtonElement | undefined;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  const real = window.location;
  vi.stubGlobal(
    'location',
    new Proxy(
      {},
      {
        get: (_, key) => (key === 'assign' ? assign : key === 'replace' ? replace : Reflect.get(real, key)),
      },
    ),
  );
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  host.remove();
  vi.unstubAllGlobals();
});

it('is hidden where Pro is neither sold nor managed', async () => {
  await show({}, { billing: false });
  expect(host.textContent).toBe('');
});

it('offers the yearly and monthly plans, and goes to Stripe', async () => {
  api.startCheckout.mockResolvedValue({ url: 'https://pay.example/cs_1' });
  await show({});
  expect(host.textContent).toContain('2,500 pages and 2,500 short links');
  await act(async () => {
    button('$36 a year (save 40%)')!.click();
  });
  expect(api.startCheckout).toHaveBeenCalledWith('year');
  expect(assign).toHaveBeenCalledWith('https://pay.example/cs_1');
  expect(button('Opening…')?.disabled).toBe(true); // held: no second checkout
});

it('holds the plans until the email is confirmed', async () => {
  await show({}, { verified: false });
  expect(host.textContent).toContain('Confirm your email first');
  expect(button('$5 a month')!.disabled).toBe(true);
});

it('says when Pro renews or ends, and when the card needs attention', async () => {
  await show({ pro: true, status: 'active', until: '2026-11-14T00:00:00Z', manageable: true });
  expect(host.textContent).toContain('Renews');
  await show({ pro: true, status: 'active', until: '2026-11-14T00:00:00Z', cancels: true, manageable: true });
  expect(host.textContent).toContain('then free');
  await show({ pro: true, status: 'past_due', until: '2026-11-14T00:00:00Z', manageable: true });
  expect(host.textContent).toContain('Your card needs attention');
});

it('keeps Manage billing for a customer after sales stop', async () => {
  api.manageBilling.mockResolvedValue({ url: 'https://portal.example/cus_1' });
  await show({ status: 'canceled', manageable: true }, { billing: false });
  await act(async () => {
    button('Manage billing')!.click();
  });
  expect(assign).toHaveBeenCalledWith('https://portal.example/cus_1');
});

it('shows why a checkout could not open', async () => {
  api.startCheckout.mockRejectedValue(new Error('down'));
  await show({});
  await act(async () => {
    button('$5 a month')!.click();
  });
  expect(host.querySelector('[role=alert]')?.textContent).toBe('down');
  expect(button('$5 a month')!.disabled).toBe(false);
});

it('back from Checkout, syncs with Stripe and reloads once Pro is on', async () => {
  history.replaceState(null, '', '/app?pro=welcome');
  api.syncBilling.mockResolvedValue({ pro: true, status: 'active' });
  await show({});
  expect(host.textContent).toContain('Payment received');
  expect(api.syncBilling).toHaveBeenCalled();
  expect(replace).toHaveBeenCalledWith('/app');
  history.replaceState(null, '', '/');
});

it('shows a free grant even where Pro is not sold', async () => {
  await show({ pro: true, source: 'comp', comp_until: '9999-12-31T00:00:00.000Z' }, { billing: false });
  expect(host.textContent).toContain('Free, on the house.');
  await show({ pro: true, source: 'comp', comp_until: '2027-03-01T00:00:00.000Z' }, { billing: false });
  expect(host.textContent).toContain('Free until');
  expect(button('Manage billing')).toBeFalsy();
});

it('says Max on a Max grant, and keeps Manage billing beside a subscription', async () => {
  const grant = { pro: true, tier: 'max', source: 'comp', comp_until: '9999-12-31T00:00:00.000Z' } as const;
  await show(grant, { billing: false });
  expect(host.textContent).toContain("You're on Max");
  expect(host.textContent).toContain('Free, on the house.');
  await show({ ...grant, status: 'active', until: '2026-11-14T00:00:00Z', manageable: true });
  expect(host.textContent).toContain("You're on Max");
  expect(button('Manage billing')).toBeTruthy();
});
