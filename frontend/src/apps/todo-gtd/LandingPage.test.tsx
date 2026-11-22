// @vitest-environment jsdom
//
// The landing page: one click makes a list and goes straight into the app (the
// browser is signed in by a cookie, nothing to save); a returning person asks for a
// sign-in link by email; on a one-list server whose list exists there is nothing to
// create, and "Reset access" appears only when the server offers it.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../core/api/client';
import type { AppConfig } from './api';
import { stubNavigation } from './stubNavigation';

const api = vi.hoisted(() => ({
  getConfig: vi.fn(),
  createList: vi.fn(),
  resetAccess: vi.fn(),
  requestSignIn: vi.fn(),
}));
vi.mock('./api', () => api);

import { LandingPage } from './LandingPage';
import { firstPage } from './settings/setup';

const OPEN: AppConfig = {
  mail: false,
  open_signup: true,
  claimed: false,
  reset: false,
  signed_in: false,
  app: 'todo',
  apps: {},
};
const NEW_LIST = { agent_token: 'AGENT', agent_url: 'https://todo.example/mcp/AGENT', tz: 'UTC', name: '' };

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let nav: ReturnType<typeof stubNavigation>;

async function mount(config: AppConfig): Promise<void> {
  api.getConfig.mockResolvedValue(config);
  await act(async () => {
    root.render(<LandingPage />);
  });
  // Todo GTD's own front page is a lazy chunk (front/TodoFront).
  await act(async () => {
    await vi.dynamicImportSettled();
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')].find((b) => b.textContent === label);
  if (!found) throw new Error(`no "${label}" button in ${JSON.stringify(host.textContent)}`);
  return found;
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
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
  vi.unstubAllGlobals();
});

describe('LandingPage', () => {
  it('offers to create a list while there is one to create, and promises no secret link', async () => {
    await mount(OPEN);
    expect(button('Start your list').disabled).toBe(false);
    expect(host.textContent).not.toContain('This list is set up');
    expect(host.textContent).not.toMatch(/shown once|web link|anyone who has a link/i);
  });

  it('links the policy pages on a hosted server', async () => {
    await mount(OPEN);
    const hrefs = [...host.querySelectorAll('nav[aria-label="Policies"] a')].map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(['/terms.html', '/privacy.html', '/refunds.html', '/support.html']);
  });

  it('leaves the Refunds page out while the suite is free', async () => {
    await mount({ ...OPEN, free: true });
    const hrefs = [...host.querySelectorAll('nav[aria-label="Policies"] a')].map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(['/terms.html', '/privacy.html', '/support.html']);
  });

  it('offers sign-in only, and no way to create, while sign-up is closed', async () => {
    await mount({ ...OPEN, mail: true, signup_closed: true });
    expect(host.textContent).toContain('Sign-up is closed');
    expect(host.querySelector('details')?.open).toBe(true);
    expect([...host.querySelectorAll('button')].map((b) => b.textContent)).toEqual(['Email me a link']);
  });

  it('links no policy page on a one-list server', async () => {
    await mount({ ...OPEN, open_signup: false });
    expect(button('Start your list').disabled).toBe(false);
    expect(host.querySelector('nav[aria-label="Policies"]')).toBeNull();
  });

  it('names no other app when the server serves none', async () => {
    await mount(OPEN);
    expect(host.querySelector('#family')).toBeNull();
    expect(host.textContent).not.toContain('Notes GTD');
    expect(host.textContent).toContain('0passwordsto remember');
  });

  it('names the other apps this server serves, each at its own address', async () => {
    await mount({
      ...OPEN,
      apps: {
        notes: { title: 'Notes GTD', url: 'https://notes.example' },
        projects: { title: 'Projects GTD', url: 'https://projects.example' },
      },
    });
    const links = [...host.querySelectorAll<HTMLAnchorElement>('#family a')].map((a) => [a.textContent, a.href]);
    expect(links).toEqual([
      ['Notes GTD', 'https://notes.example/'],
      ['Projects GTD', 'https://projects.example/'],
    ]);
    expect(host.textContent).toContain('3apps on that link:to-dos, notes, projects');
  });

  it('promises more room for an email only where there is mail and open sign-up', async () => {
    await mount({ ...OPEN, mail: true });
    expect(host.textContent).toContain('Confirm an email when you want more room.');
    expect(host.textContent).toContain('sign in on your other devices and get more room.');
  });

  it('promises no more room without mail', async () => {
    await mount(OPEN);
    expect(host.textContent).not.toContain('more room');
  });

  it('on a one-list server with no list yet, says it is yours to run and promises no more room', async () => {
    await mount({ ...OPEN, mail: true, open_signup: false });
    expect(host.textContent).toContain('Yours to run');
    expect(host.textContent).not.toContain('more room');
    expect(button('Start your list').disabled).toBe(false);
  });

  it('creates a list with one click, the name optional, and opens it on Connect your AI, once', async () => {
    api.createList.mockResolvedValue(NEW_LIST);
    await mount(OPEN);
    const name = host.querySelector<HTMLInputElement>('input:not([type])')!;
    expect(host.querySelector(`label[for="${name.id}"]`)!.textContent).toBe('Name your list (optional)');
    expect(name.required).toBe(false);
    await type(name, ' Home ');
    // The form's own button: submitting it is the path a name travels.
    const submit = host.querySelector<HTMLButtonElement>('form button[type="submit"]')!;
    expect(submit.textContent).toBe('Start your list');
    expect(submit.closest('form')!.contains(name)).toBe(true);
    await act(async () => {
      submit.click();
    });
    expect(api.createList).toHaveBeenCalledWith(expect.any(String), 'Home');
    expect(nav.replace).toHaveBeenCalledWith('/app/connect/ai?welcome');
  });

  it('creates a nameless list, and offers no email sign-in when the server has no mail', async () => {
    api.createList.mockResolvedValue(NEW_LIST);
    await mount(OPEN);
    expect(host.textContent).not.toContain('Sign in');
    expect(host.querySelector('input[type="email"]')).toBeNull();
    await act(async () => {
      button('Start your list').click();
    });
    expect(api.createList).toHaveBeenCalledWith(expect.any(String), '');
    expect(nav.replace).toHaveBeenCalledWith('/app/connect/ai?welcome');
  });

  it('shows the server’s reason when a signed-in browser tries to make another list', async () => {
    api.createList.mockRejectedValue(
      new ApiError(409, 'This browser is already signed in to a list. Sign out in Settings to make another.', 'x'),
    );
    await mount({ ...OPEN, signed_in: true });
    expect(host.querySelector('a[href="/app"]')!.textContent).toBe('Open my list');
    await act(async () => {
      button('Start your list').click();
    });
    expect(host.querySelector('[role="alert"]')!.textContent).toContain('already signed in');
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('asks for a sign-in link by email, and says the same whatever the address', async () => {
    api.requestSignIn.mockResolvedValue(undefined);
    await mount({ ...OPEN, mail: true });
    expect(host.textContent).toContain('Already have a list? Sign in');
    await type(host.querySelector<HTMLInputElement>('input[type="email"]')!, ' me@example.com ');
    await act(async () => {
      button('Email me a link').click();
    });
    expect(api.requestSignIn).toHaveBeenCalledWith('me@example.com');
    expect(host.querySelector('[role="status"]')!.textContent).toBe(
      'If a list uses that address, a sign-in link is on its way. It works once, for one hour.',
    );
  });

  it('says the list is set up, with no create button and no reset form, on a claimed server', async () => {
    await mount({ ...OPEN, open_signup: false, claimed: true });
    expect(host.textContent).toContain('This list is set up');
    expect(host.textContent).not.toContain('Start your list');
    expect(host.querySelector('input[type="password"]')).toBeNull();
    expect(host.textContent).toContain('RESET_CODE');
  });

  it('on a claimed server, offers email sign-in when there is mail', async () => {
    await mount({ ...OPEN, open_signup: false, claimed: true, mail: true });
    expect(host.textContent).toContain('Already have a list? Sign in');
  });

  it('resets access with the code and signs this browser straight in', async () => {
    api.resetAccess.mockResolvedValue(undefined);
    await mount({ ...OPEN, open_signup: false, claimed: true, reset: true });
    await type(host.querySelector<HTMLInputElement>('input[type="password"]')!, 's3cret');
    await act(async () => {
      button('Reset access').click();
    });
    expect(api.resetAccess).toHaveBeenCalledWith('s3cret');
    expect(nav.replace).toHaveBeenCalledWith('/app');
  });

  it('keeps the reset form, with the reason, when the code is wrong', async () => {
    api.resetAccess.mockRejectedValue(new ApiError(403, 'That reset code is not right.', 'x'));
    await mount({ ...OPEN, open_signup: false, claimed: true, reset: true });
    await type(host.querySelector<HTMLInputElement>('input[type="password"]')!, 'nope');
    await act(async () => {
      button('Reset access').click();
    });
    expect(host.querySelector('[role="alert"]')!.textContent).toBe('That reset code is not right.');
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('switches to "set up" when the server refuses the create because the list exists', async () => {
    api.createList.mockRejectedValue(new ApiError(409, 'This list is already set up.', 'x'));
    await mount({ ...OPEN, open_signup: false });
    await act(async () => {
      button('Start your list').click();
    });
    expect(host.textContent).toContain('This list is set up');
  });

  it('sends a new account in every app, Common Brain included, to Connect your AI once', () => {
    expect(firstPage(true)).toBe('/app/connect/ai?welcome');
    expect(firstPage(false)).toBe('/app');
  });
});
