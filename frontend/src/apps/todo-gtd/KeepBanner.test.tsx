// @vitest-environment jsdom
//
// The "keep this list" banner: only on a hosted server, while the list's email is
// unconfirmed and mail can confirm it. Dismissing it sticks for this list on this
// device; a create refused at the anonymous cap brings it back, urgent. The real
// api.ts runs against a stubbed fetch, so the cap refusal travels the same path as
// in the app — and QuickAdd shows the server's sentence, not "API error 400: …".
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
const CAP =
  'This list holds 200 todos until an email is confirmed in Settings (Connect, in Simple Sites and Common Brain). Nothing was changed.';
const KEEP = 'This list lives in this browser.';

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

describe('the keep-this-list banner', () => {
  it('asks a hosted, unconfirmed list for an email, pointing at Settings', async () => {
    await signedIn();
    await render();
    expect(banner()?.textContent).toContain(KEEP);
    expect(banner()?.textContent).toContain(
      'Add your email in Settings to keep it, use it on other devices and raise its limits.',
    );
    expect(host.querySelector('a')!.getAttribute('href')).toContain('/connect');
  });

  it.each([
    ['a one-list self-host', { hosted: false }],
    ['a server without mail', { mail: false }],
    ['a list whose email is confirmed', { email: 'me@example.com', verified: true }],
  ])('stays away on %s', async (_, session) => {
    await signedIn(session);
    await render();
    expect(host.textContent).not.toContain(KEEP);
  });

  it('stays dismissed for this list, and only this list', async () => {
    await signedIn();
    await render();
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!.click();
    });
    expect(host.textContent).not.toContain(KEEP);
    await remount();
    expect(host.textContent).not.toContain(KEEP);

    await signedIn({ list_id: 8 });
    await remount();
    expect(host.textContent).toContain(KEEP);
  });

  it('comes back urgent when a create is refused at the cap, and QuickAdd says why', async () => {
    await signedIn();
    await render();
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!.click();
    });
    expect(host.textContent).not.toContain(KEEP);

    await addTodo('one too many');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('This list is full for now.');
    expect(host.textContent).toContain(KEEP);
    expect(host.textContent).toContain(CAP);
    expect(host.textContent).not.toContain('API error 400');

    // Dismissed again, it stays away until the next refusal.
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!.click();
    });
    expect(host.textContent).not.toContain('This list is full for now.');
  });

  it('stays away when a create is refused for any other reason, and QuickAdd still says why', async () => {
    await signedIn({}, 'Title is too long');
    await render();
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!.click();
    });

    await addTodo('x');
    expect(host.textContent).toContain('Title is too long');
    expect(host.textContent).not.toContain('This list is full for now.');
    expect(host.textContent).not.toContain(KEEP);
    expect(banner()).toBeNull();
  });

  it('still works when the browser blocks storage', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    await signedIn();
    await render();
    expect(host.textContent).toContain(KEEP);
    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!.click();
    });
    expect(host.textContent).not.toContain(KEEP);
  });
});
