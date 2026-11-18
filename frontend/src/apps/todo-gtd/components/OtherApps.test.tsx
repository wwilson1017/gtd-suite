// @vitest-environment jsdom
//
// Apps, under Connect: every app with an address, each with an on/off switch that
// writes through the session store, and an Open button for the others. Hidden while
// this is the only app.
import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(),
  setApp: vi.fn(),
  createSignInLink: vi.fn(),
}));
vi.mock('../api', () => api);

import { bootstrap, resetSession, useSession } from '../session';
import { OtherApps } from './OtherApps';

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
const TWO = {
  app: 'todo',
  apps: {
    todo: { title: 'Todo GTD', url: 'https://todo.example' },
    projects: { title: 'Projects GTD', url: 'https://projects.example' },
  },
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let seen: string[] = [];

function Probe() {
  const apps = useSession().session?.apps;
  useEffect(() => {
    seen = apps ?? [];
  }, [apps]);
  return null;
}

async function show(config: object) {
  api.getConfig.mockResolvedValue(config);
  resetSession();
  api.getSession.mockResolvedValue(SESSION);
  await act(async () => {
    await bootstrap();
  });
  await act(async () => {
    root.render(
      <>
        <OtherApps />
        <Probe />
      </>,
    );
  });
}

const boxes = () => [...host.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  host.remove();
});

describe('Apps', () => {
  it('is hidden while this is the only app with an address', async () => {
    await show({ app: 'todo', apps: { todo: TWO.apps.todo } });
    expect(host.textContent).toBe('');
  });

  it('shows each app on or off, and a switch turns one on through the session', async () => {
    await show(TWO);
    expect(boxes().map((b) => b.checked)).toEqual([true, false]);
    expect(host.textContent).toContain('Projects GTD is off');
    api.setApp.mockResolvedValue({ apps: ['todo', 'projects'] });
    await act(async () => {
      boxes()[1].click();
    });
    expect(api.setApp).toHaveBeenCalledWith('projects', true);
    expect(seen).toEqual(['todo', 'projects']);
    expect(boxes().map((b) => b.checked)).toEqual([true, true]);
  });

  it('lists the app of this page even when it has no address of its own', async () => {
    // A self-host with no PUBLIC_BASE_URL: todo is served at the request's address.
    await show({ app: 'todo', apps: { projects: TWO.apps.projects } });
    expect(host.textContent).toContain('Todo GTD is on');
    expect(boxes().map((b) => b.checked)).toEqual([true, false]);
    expect([...host.querySelectorAll('button')].map((b) => b.textContent)).toEqual(['Open Projects GTD →']);
  });

  it('says so when a switch fails, and changes nothing', async () => {
    await show(TWO);
    api.setApp.mockRejectedValue(new Error('down'));
    await act(async () => {
      boxes()[1].click();
    });
    expect(host.querySelector('[role=alert]')).not.toBeNull();
    expect(seen).toEqual(['todo']);
  });

  it('offers to open only the other apps, and stays busy while the page goes there', async () => {
    await show(TWO);
    const open = [...host.querySelectorAll('button')];
    expect(open.map((b) => b.textContent)).toEqual(['Open Projects GTD →']);
    const assign = vi.fn();
    vi.stubGlobal('location', { assign });
    api.createSignInLink.mockResolvedValue({ url: 'https://projects.example/signin/T' });
    await act(async () => {
      open[0].click();
    });
    expect(assign).toHaveBeenCalledWith('https://projects.example/signin/T');
    // A second press would mint a second sign-in link.
    expect(open[0].disabled).toBe(true);
    vi.unstubAllGlobals();
  });
});
