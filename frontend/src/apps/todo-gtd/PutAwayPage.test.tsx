// @vitest-environment jsdom
//
// The page a put-away list shows instead of the app. Archived: "Bring it back"
// restores the list (naming it in X-List) and reloads into the app. Removed: only a
// confirmed email brings it back, so the page asks for one. Either way, signing out
// to start a new list is offered behind a confirm, so nobody is stuck here. The real
// api.ts and session.ts run against a stubbed fetch, so the requests and the store's
// reaction to a refusal are the app's own.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PutAwayPage } from './PutAwayPage';
import { bootstrap, resetSession } from './session';
import { stubNavigation } from './stubNavigation';
import type { Session } from './types';

const SESSION: Session = {
  list_id: 7,
  state: 'archived',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['todo'],
};
const ARCHIVED = 'Your list was put away after 60 days without use. Nothing was removed.';
const REMOVED = 'Put away for good after 180 days without use. Nothing was deleted.';
const SENT = 'Check your inbox: we sent a link to me@example.com';
const PENDING = 'If this email already has an account, the link takes you back to it.';

type Answer = { status: number; body: unknown };
/** What each "METHOD path" answers; a function sees the request body. */
let server: Record<string, Answer | ((body: Record<string, unknown>) => Answer)>;
let fetchMock: ReturnType<typeof vi.fn>;
let nav: ReturnType<typeof stubNavigation>;
let host: HTMLDivElement;
let root: Root;

function requests() {
  return fetchMock.mock.calls.map(([url, init]) => ({
    call: `${(init as RequestInit | undefined)?.method ?? 'GET'} ${String(url)}`,
    xList: ((init as RequestInit | undefined)?.headers as Record<string, string>)['X-List'],
  }));
}

/** Sign the store in to a list in ``state``, as SessionGate does, and show the page. */
async function showFor(state: Session['state']) {
  server['GET /api/app/session'] = { status: 200, body: { ...SESSION, state } };
  await act(async () => {
    await bootstrap();
  });
  await act(async () => {
    root.render(<PutAwayPage />);
  });
}

const button = (label: string) => {
  const found = [...host.querySelectorAll('button')].find((b) => b.textContent === label);
  if (!found) throw new Error(`no "${label}" button in ${JSON.stringify(host.textContent)}`);
  return found;
};
const click = (label: string) =>
  act(async () => {
    button(label).click();
  });
const text = () => host.textContent?.replace(/\s+/g, ' ') ?? '';

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  resetSession();
  server = {};
  fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const route = server[`${init.method ?? 'GET'} ${url}`];
    const { status, body } =
      typeof route === 'function'
        ? route(JSON.parse(String(init.body ?? '{}')))
        : (route ?? { status: 404, body: { detail: 'Not found' } });
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  nav = stubNavigation();
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

describe('an archived list', () => {
  it('says nothing was removed and brings the list back with one button', async () => {
    server['POST /api/app/restore'] = { status: 200, body: { state: 'active' } };
    await showFor('archived');
    expect(text()).toContain(ARCHIVED);
    expect(host.querySelector('input[type="email"]')).toBeNull();

    await click('Bring it back');
    expect(requests().at(-1)).toEqual({ call: 'POST /api/app/restore', xList: '7' });
    expect(nav.reload).toHaveBeenCalledTimes(1); // back into the app, booted afresh
  });

  it('turns into the removed page when the list was put away for good meanwhile', async () => {
    server['POST /api/app/restore'] = { status: 403, body: { detail: { state: 'removed' } } };
    await showFor('archived');
    await click('Bring it back');
    expect(nav.reload).not.toHaveBeenCalled();
    expect(text()).toContain(REMOVED);
    expect(host.querySelector('input[type="email"]')).not.toBeNull();
    // The 403 that switched the page is not an error to show.
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });
});

describe('a removed list', () => {
  const input = () => host.querySelector<HTMLInputElement>('input[type="email"]')!;

  it('asks for an email, then waits for the confirmation link, with Send again', async () => {
    server['PUT /api/app/email'] = (body) => ({
      status: 200,
      body: { email: body.email, verified: false, sent: true },
    });
    await showFor('removed');
    expect(text()).toContain(REMOVED);
    expect(text()).toContain('Add your email and confirm it to bring the list back — it then stays for good.');
    expect(text()).toContain('Your agent and capture links are off until then.');
    expect(() => button('Bring it back')).toThrow();

    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input(), 'me@example.com');
      input().dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(requests().at(-1)).toEqual({ call: 'PUT /api/app/email', xList: '7' });
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)![1].body))).toEqual({ email: 'me@example.com' });
    expect(text()).toContain(SENT);
    expect(text()).toContain(PENDING);

    await click('Send again');
    expect(requests().filter((r) => r.call === 'PUT /api/app/email')).toHaveLength(2);
    expect(text()).toContain('Sent.');
  });
});

describe.each(['archived', 'removed'] as const)('signing out of an %s list', (state) => {
  it('asks first, then signs out and goes home to start a new list', async () => {
    server['POST /api/app/signout'] = { status: 200, body: { ok: true } };
    await showFor(state);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await click('Sign out and start a new list');
    expect(confirm.mock.calls[0][0]).toMatch(/stays put away and comes back the same way later/);
    expect(confirm.mock.calls[0][0]).toMatch(/no way back in after signing out/);
    expect(requests().filter((r) => r.call.startsWith('POST'))).toEqual([]);

    confirm.mockReturnValue(true);
    await click('Sign out and start a new list');
    expect(requests().at(-1)).toEqual({ call: 'POST /api/app/signout', xList: '7' });
    expect(nav.replace).toHaveBeenCalledWith('/');
  });
});

describe('when a request fails', () => {
  it('shows the message and lets the person try again', async () => {
    server['POST /api/app/restore'] = { status: 500, body: { detail: 'The server fell over' } };
    await showFor('archived');
    await click('Bring it back');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('The server fell over');
    expect(button('Bring it back').disabled).toBe(false);
    expect(nav.reload).not.toHaveBeenCalled();
  });

  it('says so when signing out fails and keeps the person on the page', async () => {
    server['POST /api/app/signout'] = { status: 500, body: { detail: 'Could not reach the server' } };
    await showFor('removed');
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await click('Sign out and start a new list');
    // The server's own text when it gives one (apiErrorMessage prefers detail).
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Could not reach the server');
    expect(button('Sign out and start a new list').disabled).toBe(false);
    expect(nav.replace).not.toHaveBeenCalled();
  });
});
