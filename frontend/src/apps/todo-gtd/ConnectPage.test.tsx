// @vitest-environment jsdom
//
// Settings (the ⚙, at /connect): the list's email in its three states (none, waiting
// for confirmation, confirmed), read and written through the session store; signing in
// on another device by QR code; signing this device out; and no web link anywhere. The
// agent link's card is defined here too (always shown, copyable, regenerated on its
// own, filled into every tool's setup steps), but it is on Your AI, not on this page.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stubNavigation } from './stubNavigation';
import type { Session } from './types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getAgentLink: vi.fn(),
  regenerateAgentLink: vi.fn(),
  getCaptureLink: vi.fn(),
  regenerateCaptureLink: vi.fn(),
  setTz: vi.fn(),
  setEmail: vi.fn(),
  setName: vi.fn(),
  createSignInLink: vi.fn(),
  signOut: vi.fn(),
  signOutEverywhere: vi.fn(),
  // OtherApps asks which apps exist; none but this one here.
  getConfig: vi.fn(async () => ({ app: 'todo', apps: {} })),
}));
// A full mock, not a partial one over the real module: the real api.ts imports
// session.ts, which would then bind to the real getSession instead of this one.
vi.mock('./api', () => api);
vi.mock('./useTodoMeta', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useTodoMeta: () => ({
    filters: { name: 'Home', contexts: [], tags: [], status_counts: {} },
    projects: [],
    loaded: true,
    refreshMeta: async () => {},
  }),
}));

import { AgentLink, ConnectPage, EmailSection, ListName, SignInElsewhere, ThisDevice } from './ConnectPage';
import { bootstrap, resetSession } from './session';

const OLD = 'https://todo.example/link/OLD';
const NEW = 'https://todo.example/link/NEW';
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

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let nav: ReturnType<typeof stubNavigation>;

/** Sign the store in, as SessionGate does before any page renders. */
async function signedIn(session: Partial<Session> = {}) {
  resetSession();
  api.getSession.mockResolvedValue({ ...SESSION, ...session });
  await act(async () => {
    await bootstrap();
  });
}

async function render(node: React.ReactNode) {
  await act(async () => {
    root.render(node);
  });
}

const field = () => host.querySelector<HTMLInputElement>('input[readonly]')!;
const button = (label: string) => {
  const found = [...host.querySelectorAll('button')].find((b) => b.textContent === label);
  if (!found) throw new Error(`no "${label}" button in ${JSON.stringify(host.textContent)}`);
  return found;
};

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  nav = stubNavigation();
  api.getAgentLink.mockResolvedValue({ url: OLD, token: 'OLD' });
  api.regenerateAgentLink.mockResolvedValue({ url: NEW, token: 'NEW' });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await signedIn();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('the agent link card', () => {
  beforeEach(async () => {
    await render(<AgentLink />);
  });

  it('shows the real link, with a copy button, and fills it into every tool’s steps', () => {
    expect(field().value).toBe(OLD);
    expect(host.querySelector('button[aria-label="Copy the agent link"]')).not.toBeNull();
    expect(host.textContent).toContain(`claude mcp add --transport http gtd ${OLD}`);
    expect(host.textContent).toContain(`codex mcp add gtd --url ${OLD}`);
    // The paste-into-an-agent message carries it too, and has its own copy button.
    expect(host.textContent).toContain(`Open ${OLD} and show me my next actions.`);
    expect(host.querySelector('button[aria-label="Copy the message for an AI agent"]')).not.toBeNull();
    expect(host.textContent).not.toContain('YOUR-AGENT-LINK');
    // The one-click installs carry it too.
    const deeplinks = [...host.querySelectorAll('a')].map((a) => a.getAttribute('href')!);
    expect(deeplinks.some((h) => h.startsWith('cursor://'))).toBe(true);
    expect(deeplinks.some((h) => h.startsWith('vscode:mcp/install?') && decodeURIComponent(h).includes(OLD))).toBe(
      true,
    );
  });

  it('says what it reaches in each app the account turned on', async () => {
    expect(host.textContent).toContain('read, add and update your todos.');
    await act(async () => {
      root.unmount();
    });
    root = createRoot(host);
    await signedIn({ apps: ['todo', 'sites', 'notes'] });
    await render(<AgentLink />);
    expect(host.textContent).toContain('your todos, pages, short links, and notes.');
  });

  it('regenerates only after a confirm that says AI tools must be re-added', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await act(async () => {
      button('Regenerate').click();
    });
    expect(confirm.mock.calls[0][0]).toMatch(/must be re-added/);
    expect(confirm.mock.calls[0][0]).toMatch(/capture link is not affected/);
    expect(confirm.mock.calls[0][0]).not.toMatch(/web link/);
    expect(api.regenerateAgentLink).not.toHaveBeenCalled();
    expect(field().value).toBe(OLD);

    confirm.mockReturnValue(true);
    await act(async () => {
      button('Regenerate').click();
    });
    expect(api.regenerateAgentLink).toHaveBeenCalledTimes(1);
    expect(field().value).toBe(NEW);
    expect(host.textContent).toContain(`claude mcp add --transport http gtd ${NEW}`);
    expect(host.textContent).toContain(`Open ${NEW} and show me my next actions.`);
    expect(host.textContent).not.toContain(OLD);
  });
});

// The email card has three states, and the limits it quotes come from the session.
// (The card itself is only rendered when the server can send mail.)
describe('the email in Settings', () => {
  const NONE = 'Add your email to keep this list, use it on other devices and raise its limits.';
  const PENDING =
    'Not confirmed yet — check your inbox. If this email already has an account, the link takes you back to it.';
  const CONFIRMED = 'Confirmed: this list is permanent.';
  const input = () => host.querySelector<HTMLInputElement>('input[type="email"]')!;

  async function save(value: string) {
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input(), value);
      input().dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
  }

  it('asks for an email, quoting this list’s limits, and waits for the link once one is saved', async () => {
    api.setEmail.mockImplementation(async (email: string) => ({
      email: email || null,
      verified: false,
      sent: email !== '',
      caps: { todos: 200, projects: 20, areas: 10 },
    }));
    await render(<EmailSection />);
    expect(host.textContent).toContain(NONE);
    expect(host.textContent).toContain('Until then it holds up to 200 todos, 20 projects and 10 areas.');
    expect(host.textContent).not.toContain(PENDING);

    await save('me@example.com');
    expect(api.setEmail).toHaveBeenCalledWith('me@example.com');
    expect(host.textContent).toContain(PENDING);
    expect(host.textContent).toContain(
      'Saved. Check your inbox: if this email already has an account, the link takes you back to it.',
    );
    expect(host.textContent).not.toContain(NONE);
    expect(input().value).toBe('me@example.com');

    await save('');
    expect(host.textContent).toContain(NONE);
  });

  it('sends the link again for the same address, or says to wait', async () => {
    await signedIn({ email: 'me@example.com' });
    api.setEmail
      .mockResolvedValueOnce({
        email: 'me@example.com',
        verified: false,
        sent: true,
        caps: { todos: 200, projects: 20, areas: 10 },
      })
      .mockResolvedValueOnce({
        email: 'me@example.com',
        verified: false,
        sent: false,
        caps: { todos: 200, projects: 20, areas: 10 },
      });
    await render(<EmailSection />);
    expect(host.textContent).toContain(PENDING);

    await act(async () => {
      button('Send again').click();
    });
    expect(api.setEmail).toHaveBeenLastCalledWith('me@example.com');
    expect(host.textContent).toContain('Sent.');

    await act(async () => {
      button('Send again').click();
    });
    expect(host.textContent).toContain('Wait a few minutes before sending again.');
    expect(host.textContent).toContain(PENDING);
  });

  it('says a confirmed list is permanent and quotes its larger limits', async () => {
    await signedIn({ email: 'me@example.com', verified: true, caps: { todos: 5000, projects: 1000, areas: 100 } });
    await render(<EmailSection />);
    expect(host.textContent).toContain(CONFIRMED);
    expect(host.textContent).toContain('It holds up to 5,000 todos, 1,000 projects and 100 areas.');
    expect(host.textContent).not.toContain('Send again');
    expect(input().value).toBe('me@example.com');
  });

  it('starts over when a confirmed list gets a new address', async () => {
    await signedIn({ email: 'me@example.com', verified: true, caps: { todos: 5000, projects: 1000, areas: 100 } });
    api.setEmail.mockResolvedValue({
      email: 'new@example.com',
      verified: false,
      sent: true,
      caps: { todos: 200, projects: 20, areas: 10 },
    });
    await render(<EmailSection />);
    expect(host.textContent).toContain('It holds up to 5,000 todos');
    await save('new@example.com');
    expect(host.textContent).toContain(PENDING);
    expect(host.textContent).not.toContain(CONFIRMED);
    // The limits drop with it, as the server's answer says.
    expect(host.textContent).toContain('Until then it holds up to 200 todos, 20 projects and 10 areas.');
    expect(host.textContent).not.toContain('5,000');
  });

  it('says to wait when the first save mails nothing, since the address was asked for just now', async () => {
    api.setEmail.mockResolvedValue({
      email: 'me@example.com',
      verified: false,
      sent: false,
      caps: { todos: 200, projects: 20, areas: 10 },
    });
    await render(<EmailSection />);
    await save('me@example.com');
    expect(host.textContent).toContain(PENDING);
    expect(host.querySelector('[role="status"]')!.textContent).toBe(
      'Saved. Wait a few minutes, then press Send again.',
    );
    expect(button('Send again')).toBeTruthy();
  });

  it('just says Saved when a confirmed list saves its address again, with nothing to send', async () => {
    await signedIn({ email: 'me@example.com', verified: true, caps: { todos: 5000, projects: 1000, areas: 100 } });
    api.setEmail.mockResolvedValue({
      email: 'me@example.com',
      verified: true,
      sent: false,
      caps: { todos: 5000, projects: 1000, areas: 100 },
    });
    await render(<EmailSection />);
    await save('me@example.com');
    expect(host.querySelector('[role="status"]')!.textContent).toBe('Saved.');
    expect(host.textContent).toContain(CONFIRMED);
    expect(host.textContent).not.toContain('Send again');
  });

  it('shows the server’s message when an address is refused, and keeps what was typed', async () => {
    api.setEmail.mockRejectedValueOnce(new Error('Enter a valid email address'));
    await render(<EmailSection />);
    await save('nope');
    expect(host.querySelector('[role="status"]')!.textContent).toBe('Enter a valid email address');
    expect(host.textContent).not.toContain('Saved');
    expect(input().value).toBe('nope');
    expect(host.textContent).not.toContain(PENDING);
  });

  it('quotes no limits on a one-list server, where an email does not change them', async () => {
    await signedIn({ hosted: false, caps: { todos: 20000, projects: 1000, areas: 100 } });
    await render(<EmailSection />);
    expect(host.textContent).toContain('Add your email to keep this list, use it on other devices.');
    expect(host.textContent).not.toContain('holds up to');
  });
});

describe('the list name in Settings', () => {
  it('keeps the stored name when Save is pressed without editing', async () => {
    api.setName.mockImplementation(async (name: string) => name);
    await render(<ListName />);
    expect(host.querySelector<HTMLInputElement>('input')!.value).toBe('Home');
    await act(async () => {
      host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(api.setName).toHaveBeenCalledWith('Home');
  });
});

describe('signing in on another device', () => {
  it('shows a QR code and the link, says plainly who it lets in, and can make a new one', async () => {
    api.createSignInLink
      .mockResolvedValueOnce({ url: 'https://todo.example/signin/ONE', expires_at: 'x' })
      .mockResolvedValueOnce({ url: 'https://todo.example/signin/TWO', expires_at: 'x' });
    await render(<SignInElsewhere />);
    expect(host.querySelector('svg')).toBeNull(); // nothing is issued until asked
    expect(host.textContent).toContain('anyone who scans it gets into this list');
    expect(host.textContent).toContain('works once');

    await act(async () => {
      button('Show a sign-in code').click();
    });
    expect(host.querySelector('svg')).not.toBeNull();
    expect(field().value).toBe('https://todo.example/signin/ONE');
    expect(host.querySelector('button[aria-label="Copy the sign-in link"]')).not.toBeNull();

    await act(async () => {
      button('Make a new code').click();
    });
    expect(field().value).toBe('https://todo.example/signin/TWO');
  });
});

describe('signing this device out', () => {
  it('is blunt when the list has no email, and goes home once signed out', async () => {
    api.signOut.mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await render(<ThisDevice />);
    await act(async () => {
      button('Sign out').click();
    });
    expect(confirm.mock.calls[0][0]).toMatch(/no way back into it after signing out/);
    expect(api.signOut).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    await act(async () => {
      button('Sign out').click();
    });
    expect(api.signOut).toHaveBeenCalledTimes(1);
    expect(nav.replace).toHaveBeenCalledWith('/');
  });

  it('is just as blunt while the email is not confirmed: no sign-in mail goes to it', async () => {
    await signedIn({ email: 'me@example.com' });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await render(<ThisDevice />);
    await act(async () => {
      button('Sign out').click();
    });
    expect(confirm.mock.calls[0][0]).toMatch(/no confirmed email, so there is no way back/);
  });

  it('points at the email once it is confirmed, and signs out everywhere on its own button', async () => {
    api.signOutEverywhere.mockResolvedValue(undefined);
    await signedIn({ email: 'me@example.com', verified: true });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await render(<ThisDevice />);
    await act(async () => {
      button('Sign out everywhere').click();
    });
    expect(confirm.mock.calls[0][0]).toMatch(/Every device signed in to this list is signed out/);
    expect(confirm.mock.calls[0][0]).toMatch(/Sign back in with your email/);
    expect(api.signOutEverywhere).toHaveBeenCalledTimes(1);
    expect(api.signOut).not.toHaveBeenCalled();
    expect(nav.replace).toHaveBeenCalledWith('/');
  });

  it('is blunt about signing out everywhere without an email', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await render(<ThisDevice />);
    await act(async () => {
      button('Sign out everywhere').click();
    });
    expect(confirm.mock.calls[0][0]).toMatch(/no way back into it after signing out everywhere/);
    expect(api.signOutEverywhere).not.toHaveBeenCalled();
  });
});

describe('the whole Settings page', () => {
  it('goes straight to the email field when opened from an "Add your email" link', async () => {
    api.getCaptureLink.mockResolvedValue({ url: 'https://todo.example/c/CAP', token: 'CAP' });
    window.matchMedia = ((q: string) => ({
      matches: false,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    await render(
      <MemoryRouter initialEntries={['/connect#email']}>
        <ConnectPage />
      </MemoryRouter>,
    );
    const input = host.querySelector<HTMLInputElement>('input[type="email"]')!;
    expect(document.activeElement).toBe(input);
    expect(scroll.mock.contexts[0]).toBe(input);
  });

  it('shows the account number on a server with no mail, where the email section is gone', async () => {
    api.getCaptureLink.mockResolvedValue({ url: 'https://todo.example/c/CAP', token: 'CAP' });
    window.matchMedia = ((q: string) => ({
      matches: false,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;
    await signedIn({ account_no: '1234-5678', mail: false });
    await render(
      <MemoryRouter>
        <ConnectPage />
      </MemoryRouter>,
    );
    expect(host.textContent).toContain('Account number1234-5678');
    expect(host.textContent).not.toContain('Your email');
  });

  it('has no web link anywhere, and offers the sign-in code and sign-out', async () => {
    api.getCaptureLink.mockResolvedValue({ url: 'https://todo.example/c/CAP', token: 'CAP' });
    window.matchMedia = ((q: string) => ({
      matches: false,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;
    await render(
      <MemoryRouter>
        <ConnectPage />
      </MemoryRouter>,
    );
    expect(host.textContent).not.toMatch(/web link/i);
    expect(host.textContent).toContain('Sign in on another device');
    expect(host.textContent).toContain('Your email');
    expect(button('Sign out everywhere')).toBeTruthy();
  });

  it('keeps everything but connecting an AI, which has its own page', async () => {
    api.getCaptureLink.mockResolvedValue({ url: 'https://todo.example/c/CAP', token: 'CAP' });
    window.matchMedia = ((q: string) => ({
      matches: false,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;
    await render(
      <MemoryRouter>
        <ConnectPage />
      </MemoryRouter>,
    );
    expect(api.getAgentLink).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain('Connect your AI to GTD');
    expect(host.textContent).not.toContain(OLD);
    expect(host.querySelector('[role="tab"]')).toBeNull();
    for (const kept of ['Appearance', 'Capture link', 'List name', 'Time zone', 'Daily brain tickle', 'This device']) {
      expect(host.textContent).toContain(kept);
    }
    // The header says so: Your AI beside the gear, which is Settings.
    expect(host.querySelector('a[href="/ai"]')!.textContent).toBe('Your AI');
    expect(host.querySelector('a[href="/connect"]')!.getAttribute('aria-label')).toBe('Settings');
  });
});
