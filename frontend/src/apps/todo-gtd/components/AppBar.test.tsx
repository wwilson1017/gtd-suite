// @vitest-environment jsdom
//
// The suite's app bar and its hops (hop.ts): the family, this app and the apps the
// account has on are tabs, in the bar's order, this one marked; the rest wait in
// More; on an app's old address the bar is a notice. Another app is a plain link to
// its /app carrying this list's id. Arriving there: the same list stays, another list or none goes back for
// a sign-in link, and #to= mints one and goes. Never an address from the URL.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stubNavigation } from '../stubNavigation';
import type { Session } from '../types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(),
  createSignInLink: vi.fn(),
}));
vi.mock('../api', () => api);

import { readHop, settleHop } from '../hop';
import { SessionGate } from '../PublicTodoApp';
import { bootstrap, resetSession } from '../session';
import { AppBar } from './AppBar';

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
const SUITE = {
  app: 'todo',
  apps: {
    sites: { title: 'Simple Sites', url: 'https://sites.example' },
    todo: { title: 'Todo GTD', url: 'https://todo.example' },
    notes: { title: 'Notes GTD', url: 'https://notes.example' },
  },
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let nav: ReturnType<typeof stubNavigation>;

async function signIn() {
  resetSession();
  api.getSession.mockResolvedValue(SESSION);
  await act(async () => {
    await bootstrap();
  });
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  // One config for the whole file: hop.ts asks once per page load.
  api.getConfig.mockResolvedValue(SUITE);
  nav = stubNavigation();
  history.replaceState(null, '', '/app');
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

describe('the app bar', () => {
  it('makes the family tabs, on or off, this one marked, and keeps an app that is off in More', async () => {
    await signIn();
    await act(async () => {
      root.render(<AppBar />);
    });
    const items = [...host.querySelectorAll('nav[aria-label="Apps"] > *')];
    // Notes is off for this account and still a tab: its address shows how to turn it on.
    expect(items.map((i) => i.textContent)).toEqual(['Todo', 'Notes']);
    expect(items[0].getAttribute('aria-current')).toBe('page');
    expect(items[0].tagName).toBe('SPAN');
    expect(items[1].getAttribute('href')).toBe('https://notes.example/app#from=todo.7');

    const more = [...host.querySelectorAll('button')].find((b) => b.textContent?.startsWith('More'))!;
    expect(host.textContent).not.toContain('Simple Sites');
    await act(async () => {
      more.click();
    });
    const offered = [...document.getElementById(more.getAttribute('aria-controls')!)!.querySelectorAll('a')];
    expect(offered.map((a) => a.getAttribute('href'))).toEqual(['https://sites.example/app#from=todo.7']);
    expect(offered[0].textContent).toBe('Simple Sites' + 'A place to park the pages your AI makes.');
  });

  it('makes an app the account has on a tab, and drops More when nothing is left for it', async () => {
    resetSession();
    api.getSession.mockResolvedValue({ ...SESSION, apps: ['todo', 'sites'] });
    await act(async () => {
      await bootstrap();
    });
    await act(async () => {
      root.render(<AppBar />);
    });
    const items = [...host.querySelectorAll('nav[aria-label="Apps"] > *')];
    expect(items.map((i) => i.textContent)).toEqual(['Todo', 'Notes', 'Sites']);
    expect([...host.querySelectorAll('button')].some((b) => b.textContent?.startsWith('More'))).toBe(false);
  });
});

describe("the app bar on an app's old address", () => {
  it('is a notice with one button, which mints a sign-in link for this app and goes there', async () => {
    vi.resetModules();
    api.getConfig.mockResolvedValue({ ...SUITE, moved: 'https://todo.example/notes' });
    api.createSignInLink.mockResolvedValue({ url: 'https://todo.example/notes/signin/T', expires_at: '' });
    const { AppBar: Bar } = await import('./AppBar');
    const session = await import('../session');
    session.resetSession();
    api.getSession.mockResolvedValue(SESSION);
    await act(async () => {
      await session.bootstrap();
    });
    await act(async () => {
      root.render(<Bar />);
    });
    expect(host.querySelector('nav')).toBeNull();
    expect(host.querySelectorAll('a')).toHaveLength(0);
    expect(host.textContent).toContain('now lives at todo.example/notes');
    await act(async () => {
      host.querySelector('button')!.click();
    });
    // This page's app: the link opens it at its new address, on this account.
    expect(api.createSignInLink).toHaveBeenCalledWith('todo');
    expect(nav.replace).toHaveBeenCalledWith('https://todo.example/notes/signin/T');
  });
});

describe('the app bar where this app has no address', () => {
  it('stays hidden: a hop could not come back here for a sign-in link', async () => {
    vi.resetModules();
    api.getConfig.mockResolvedValue({ app: 'todo', apps: { notes: SUITE.apps.notes } });
    const { AppBar: Bar } = await import('./AppBar');
    const session = await import('../session');
    session.resetSession();
    api.getSession.mockResolvedValue(SESSION);
    await act(async () => {
      await session.bootstrap();
    });
    await act(async () => {
      root.render(<Bar />);
    });
    expect(host.querySelector('nav')).toBeNull();
  });
});

describe('a hop', () => {
  it('reads only the two marks it makes', () => {
    expect(readHop('#from=notes.9')).toEqual({ from: 'notes', list: 9 });
    expect(readHop('#to=sites')).toEqual({ to: 'sites' });
    expect(readHop('#from=https://evil.example')).toBeNull();
    expect(readHop('#top')).toBeNull();
  });

  it('arriving signed in to the same list: stays, and drops the mark', async () => {
    history.replaceState(null, '', '/app#from=notes.7');
    expect(await settleHop({ from: 'notes', list: 7 }, 7)).toBe('stay');
    expect(nav.replace).not.toHaveBeenCalled();
    expect(window.location.hash).toBe('');
  });

  it('arriving signed in to another list, or signed out: back to where it came from for a link', async () => {
    expect(await settleHop({ from: 'notes', list: 9 }, 7)).toBe('away');
    expect(await settleHop({ from: 'notes', list: 9 }, null)).toBe('away');
    expect(nav.replace.mock.calls).toEqual([
      ['https://notes.example/app#to=todo'],
      ['https://notes.example/app#to=todo'],
    ]);
  });

  it('from an app the server does not list: stays', async () => {
    expect(await settleHop({ from: 'projects', list: 9 }, null)).toBe('stay');
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it('#to= mints a sign-in link for that app and goes to it; signed out, nothing', async () => {
    api.createSignInLink.mockResolvedValue({ url: 'https://sites.example/signin/T', expires_at: '' });
    expect(await settleHop({ to: 'sites' }, 7)).toBe('away');
    expect(api.createSignInLink).toHaveBeenCalledWith('sites');
    expect(nav.replace).toHaveBeenCalledWith('https://sites.example/signin/T');
    expect(await settleHop({ to: 'sites' }, null)).toBe('stay');
    expect(api.createSignInLink).toHaveBeenCalledTimes(1);
  });

  it('SessionGate shows nothing while a hop leaves, and the app once it has arrived', async () => {
    history.replaceState(null, '', '/app#from=notes.9');
    resetSession();
    api.getSession.mockResolvedValue(SESSION);
    await act(async () => {
      root.render(
        <SessionGate>
          <p>the app</p>
        </SessionGate>,
      );
    });
    expect(nav.replace).toHaveBeenCalledWith('https://notes.example/app#to=todo');
    expect(host.textContent).toBe('');

    await act(async () => {
      root.unmount();
    });
    root = createRoot(host);
    history.replaceState(null, '', '/app#from=notes.7');
    resetSession();
    await act(async () => {
      root.render(
        <SessionGate>
          <p>the app</p>
        </SessionGate>,
      );
    });
    expect(host.textContent).toBe('the app');
    expect(window.location.hash).toBe('');
  });

  it('SessionGate settles a hop into another account that is put away, too', async () => {
    history.replaceState(null, '', '/app#from=notes.9');
    resetSession();
    api.getSession.mockResolvedValue({ ...SESSION, state: 'archived' });
    await act(async () => {
      root.render(
        <SessionGate>
          <p>the app</p>
        </SessionGate>,
      );
    });
    expect(nav.replace).toHaveBeenCalledWith('https://notes.example/app#to=todo');
    expect(host.textContent).toBe('');
  });
});

describe('a hop whose way back cannot be found', () => {
  it('shows nothing of the other account, keeps the mark, and offers a retry', async () => {
    vi.resetModules();
    api.getConfig.mockRejectedValue(new Error('offline'));
    const { SessionGate: Gate } = await import('../PublicTodoApp');
    const session = await import('../session');
    history.replaceState(null, '', '/app#from=notes.9');
    session.resetSession();
    api.getSession.mockResolvedValue(SESSION);
    await act(async () => {
      root.render(
        <Gate>
          <p>the other account</p>
        </Gate>,
      );
    });
    expect(host.textContent).not.toContain('the other account');
    expect(host.querySelector('[role=alert]')?.textContent).toContain('Could not finish opening this app');
    expect(window.location.hash).toBe('#from=notes.9');
    expect(nav.replace).not.toHaveBeenCalled();
  });
});
