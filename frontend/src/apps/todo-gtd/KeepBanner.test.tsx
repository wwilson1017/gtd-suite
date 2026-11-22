// @vitest-environment jsdom
//
// "This list is full": only after a create was refused at the anonymous cap, on a hosted
// server, while the list's email is unconfirmed and mail can confirm it. Until then
// nothing shows (the header's next-step button asks for the email). The real api.ts runs
// against a stubbed fetch, so the cap refusal travels the same path as in the app — and
// QuickAdd shows the server's sentence, not "API error 400: …".
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QuickAdd } from './components/QuickAdd';
import { KeepBanner } from './KeepBanner';
import { bootstrap, resetSession } from './session';
import type { Session } from './types';

const SESSION: Session = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['todo'],
};
const CAP = 'This list holds 200 todos until an email is confirmed in Settings. Nothing was changed.';
const FULL = 'This list is full for now.';

let host: HTMLDivElement;
let root: Root;

function answer(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

async function signedIn(session: Partial<Session> = {}, refusal = CAP) {
  resetSession();
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      url === '/api/app/session' ? answer(200, { ...SESSION, ...session }) : answer(400, { detail: refusal }),
    ),
  );
  await act(async () => {
    await bootstrap();
  });
}

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <KeepBanner />
        <QuickAdd onAdded={() => {}} />
      </MemoryRouter>,
    );
  });
}

async function remount() {
  await act(async () => {
    root.unmount();
  });
  root = createRoot(host);
  await render();
}

const banner = () => host.querySelector('[role="status"], [role="alert"]');

async function addTodo(title: string) {
  const input = host.querySelector<HTMLInputElement>('input')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, title);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => {
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function refuseOne() {
  await addTodo('one too many');
}

describe('the list-is-full alert', () => {
  it('shows nothing until a create is refused at the cap, then points at the email', async () => {
    await signedIn();
    await render();
    expect(banner()).toBeNull();

    await refuseOne();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(FULL);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(
      'Add your email to keep it, use it on other devices and raise its limits.',
    );
    expect(host.querySelector('[role="alert"] a')!.getAttribute('href')).toBe('/connect/email');
    expect(host.textContent).toContain(CAP);
    expect(host.textContent).not.toContain('API error 400');
  });

  it.each([
    ['a one-list self-host', { hosted: false }],
    ['a server without mail', { mail: false }],
    ['a list whose email is confirmed', { email: 'me@example.com', verified: true }],
  ])('stays away on %s, even at the cap', async (_, session) => {
    await signedIn(session);
    await render();
    await refuseOne();
    expect(host.textContent).not.toContain(FULL);
  });

  it('can be dismissed, and comes back with the next refusal', async () => {
    await signedIn();
    await render();
    await refuseOne();
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!.click();
    });
    expect(host.textContent).not.toContain(FULL);
    await remount();
    expect(host.textContent).not.toContain(FULL);

    await refuseOne();
    expect(host.textContent).toContain(FULL);
  });

  it('stays away when a create is refused for any other reason, and QuickAdd still says why', async () => {
    await signedIn({}, 'Title is too long');
    await render();
    await addTodo('x');
    expect(host.textContent).toContain('Title is too long');
    expect(host.textContent).not.toContain(FULL);
    expect(banner()).toBeNull();
  });
});
