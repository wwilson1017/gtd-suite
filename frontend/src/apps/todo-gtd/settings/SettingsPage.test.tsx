// @vitest-environment jsdom
//
// Settings, the page: a menu of sections in groups, each section at /connect/<key>, the
// two-step box above the open one until every step is done (and "Skip for now" only on a
// brand-new account's first visit), the menu's step badges, and on a phone a list that
// opens one section at a time. No web link anywhere.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getAiTools: vi.fn(),
  getAgentLink: vi.fn(async () => ({ url: 'https://todo.example/link/TOKEN', token: 'TOKEN' })),
  regenerateAgentLink: vi.fn(),
  getCaptureLink: vi.fn(async () => ({ url: 'https://todo.example/c/CAP', token: 'CAP' })),
  regenerateCaptureLink: vi.fn(),
  setEmail: vi.fn(),
  setName: vi.fn(),
  setTz: vi.fn(),
  createSignInLink: vi.fn(),
  signOut: vi.fn(),
  signOutEverywhere: vi.fn(),
  getConfig: vi.fn(async () => ({ app: 'todo', apps: {} })),
  todoFetch: vi.fn(async (): Promise<unknown> => ({ reads: [] })),
}));
// A full mock: the real api.ts imports session.ts, which would bind to the real getSession.
vi.mock('../api', () => api);
vi.mock('../useTodoMeta', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useTodoMeta: () => ({
    filters: { name: '', contexts: [], tags: [], status_counts: {}, tz: 'UTC' },
    projects: [],
    loaded: true,
    refreshMeta: async () => {},
  }),
}));

import { bootstrap, resetSession } from '../session';
import { TodoSettings } from '../TodoSettings';
import { useSetupOnFocus } from './setup';

const SESSION: Session = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['todo'],
  account_no: '1234-5678',
  ai_tools: [],
};
const AI = { ai_tools: [{ name: 'Claude', last_used: '2026-11-21', days_ago: 0 }] };

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let phone = false;

async function open(path: string, session: Partial<Session> = {}) {
  resetSession();
  api.getSession.mockResolvedValue({ ...SESSION, ...session });
  await act(async () => {
    await bootstrap();
  });
  await act(async () => {
    root.render(
      <MemoryRouter key={path} initialEntries={[path]}>
        <Routes>
          <Route path="/connect" element={<TodoSettings />} />
          <Route path="/connect/:section" element={<TodoSettings />} />
          <Route path="/" element={<p>the list</p>} />
        </Routes>
      </MemoryRouter>,
    );
  });
}

const box = () => host.querySelector('section[aria-label="Get set up"]');
const heading = () => host.querySelector('#settings-section')?.textContent ?? null;
const menu = () =>
  [...host.querySelectorAll('nav[aria-label="Settings"] a')].map((a) => [a.getAttribute('href'), a.textContent]);
const link = (text: string) => [...host.querySelectorAll('a')].find((a) => a.textContent === text);

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  phone = false;
  window.matchMedia = ((q: string) => ({
    // The shell's own queries never match: the top menu. Settings' phone query follows `phone`.
    matches: q === '(width < 48rem)' && phone,
    media: q,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
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

describe('Settings', () => {
  it('lists every section in its group, each at its own address', async () => {
    await open('/connect/devices');
    expect(menu()).toEqual([
      ['/connect/ai', '✦Connect your AIStep 1'],
      ['/connect/email', '✉Add your emailStep 2'],
      ['/connect/devices', '⌁Devices & sign-in'],
      ['/connect/security', '⚿Security'],
      ['/connect/install', '⌂Install on your phone'],
      ['/connect/look', '◐Appearance'],
      ['/connect/list', '☰List name & time zone'],
      ['/connect/capture', '⤓Capture link'],
      ['/connect/tickle', '✧Daily brain tickle'],
    ]);
    expect([...host.querySelectorAll('nav p')].map((p) => p.textContent)).toEqual([
      'Get started',
      'Account',
      'Todo GTD',
    ]);
    expect(heading()).toBe('Devices & sign-in');
    expect(host.querySelector('[aria-current="page"][href="/connect/devices"]')).not.toBeNull();
    expect(host.textContent).toContain('Account number1234-5678');
    expect(host.textContent).not.toMatch(/web link/i);
  });

  it('has the Enhanced security switch under Security, with what it does not do', async () => {
    await open('/connect/security');
    expect(heading()).toBe('Security');
    const text = host.querySelector('section[aria-labelledby="settings-section"]')!.textContent!;
    expect(text).toContain('The ones you already have keep working, with no end date.');
    expect(text).toContain('copies the name of a tool you already use raises no email');
    expect(text).toContain('after 50 names nothing new is recorded or emailed');
    expect(link('Add your email')!.getAttribute('href')).toBe('/connect/email');
    const box = host.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    expect(box.checked).toBe(false);
    api.todoFetch.mockImplementation(async (path?: string) =>
      path === '/security' ? { enhanced_security: true, agent_link_expired: false } : { reads: [] },
    );
    await act(async () => box.click());
    expect(api.todoFetch).toHaveBeenCalledWith('/security', { method: 'PUT', body: '{"on":true}' });
    expect(box.checked).toBe(true);

    await open('/connect/security', { email: 'me@example.com', verified: true, enhanced_security: true });
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
    expect(link('Add your email')).toBeUndefined();
    await open('/connect/security', { mail: false });
    expect(host.textContent).toContain('This server cannot send email, so it sends no alerts.');
  });

  it('lists the Common Brain reads under the switch, a page at a time, and says what the log is', async () => {
    const read = (id: number, more: object = {}) => ({
      id,
      at: '2026-11-20T15:04:00.000Z',
      by: 'Claude',
      kind: 'get',
      item_kind: 'page',
      target: `people/p${id}`,
      brain: 'Work',
      key_kind: null,
      key_name: null,
      ...more,
    });
    const first = Array.from({ length: 100 }, (_, i) => read(200 - i));
    first[0] = read(200, {
      kind: 'link',
      item_kind: 'file',
      target: 'raw/scan.pdf',
      key_kind: 'key',
      key_name: 'Nightly',
    });
    first[1] = read(199, { kind: 'search', item_kind: null, target: 'maya', key_kind: 'link', key_name: 'Reception' });
    api.todoFetch.mockImplementation(async (path?: string) => ({
      reads: path === '/security/reads' ? first : [read(100, { kind: 'connect', item_kind: null, target: '' })],
    }));
    await open('/connect/security', { enhanced_security: true });
    const text = () => host.querySelector('section[aria-labelledby="settings-section"]')!.textContent!;
    expect(text()).toContain('Common Brain reads, last 90 days');
    expect(text()).toContain('Only Common Brain reads are logged');
    expect(text()).toContain('A file row means a download link was handed out');
    expect(text()).toContain('The log is best effort');
    expect(text()).toContain('Rows are kept 90 days.');
    const cells = () =>
      [...host.querySelectorAll('tbody tr')].map((tr) => [...tr.children].map((td) => td.textContent));
    expect(cells()).toHaveLength(100);
    expect(cells()[0].slice(1)).toEqual([
      'Claude',
      'Key: Nightly',
      'Was given a download link to file raw/scan.pdf · Work',
    ]);
    expect(cells()[1].slice(1)).toEqual(['Claude', 'Staff link: Reception', 'Searched for “maya” · Work']);
    expect(cells()[2].slice(1)).toEqual(['Claude', 'Agent link', 'Read page people/p198 · Work']);
    const older = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Older')!;
    await act(async () => older.click());
    expect(api.todoFetch).toHaveBeenLastCalledWith('/security/reads?before=101');
    expect(cells()).toHaveLength(101);
    expect(cells()[100][3]).toBe('Connected: your locked memories · Work');
    // A short page is the last one.
    expect([...host.querySelectorAll('button')].find((b) => b.textContent === 'Older')).toBeUndefined();
  });

  it('says how to start the read log while there is none', async () => {
    api.todoFetch.mockImplementation(async () => ({ reads: [] }));
    await open('/connect/security');
    expect(host.textContent).toContain('Nothing logged. Turn on Enhanced security to start the log.');
    expect(host.querySelector('table')).toBeNull();
  });

  it('opens the first step still to do at /connect, else Connect your AI', async () => {
    await open('/connect');
    expect(heading()).toBe('Connect your AI');
    await open('/connect', AI);
    expect(heading()).toBe('Add your email');
    await open('/connect', { ...AI, email: 'me@example.com', verified: true });
    expect(heading()).toBe('Connect your AI');
  });

  it.each([
    ['brand new', {}, 'Get set up in two steps', '0 of 2 done', ['Start', 'Start']],
    ['an AI connected', AI, 'Get set up in two steps', '1 of 2 done', ['View', 'Start']],
    ['the email sent', { ...AI, email: 'me@example.com' }, 'Get set up in two steps', '1 of 2 done', ['View', 'Open']],
    ['no mail on the server', { mail: false }, 'One step to go', '0 of 1 done', ['Start']],
  ])('shows the two-step box above every section: %s', async (_, session, title, count, actions) => {
    await open('/connect/look', session);
    expect(box()!.querySelector('h2')!.textContent).toBe(title);
    expect(box()!.textContent).toContain(count);
    expect([...box()!.querySelectorAll('a > span:last-child')].map((s) => s.textContent)).toEqual(actions);
    expect(heading()).toBe('Appearance');
  });

  it('drops the box, and keeps the done badges, once every step is done', async () => {
    await open('/connect/ai', { ...AI, email: 'me@example.com', verified: true });
    expect(box()).toBeNull();
    expect(menu().slice(0, 2)).toEqual([
      ['/connect/ai', '✦Connect your AIDone'],
      ['/connect/email', '✉Add your emailDone'],
    ]);
    await open('/connect/ai', { ...AI, mail: false });
    expect(box()).toBeNull();
    expect(menu().map(([href]) => href)).not.toContain('/connect/email');
  });

  it('says Check inbox in the menu while the emailed link waits', async () => {
    await open('/connect/email', { ...AI, email: 'me@example.com' });
    expect(menu()[1]).toEqual(['/connect/email', '✉Add your emailCheck inbox']);
    expect(host.textContent).toContain('Check your inbox: we sent a link to me@example.com');
  });

  it('offers "Skip for now" only on a brand-new account’s first visit', async () => {
    await open('/connect/ai');
    expect(link('Skip for now, go to my list →')).toBeUndefined();
    await open('/connect/ai?welcome');
    await act(async () => {
      link('Skip for now, go to my list →')!.click();
    });
    expect(host.textContent).toBe('the list');
  });

  it('on a phone, is a list that opens one section at a time, with the way back', async () => {
    phone = true;
    await open('/connect');
    expect(heading()).toBeNull();
    expect(box()).not.toBeNull(); // above the list
    expect(menu()[2]).toEqual(['/connect/devices', '⌁Devices & sign-in›']);

    await act(async () => {
      link('⌁Devices & sign-in›')!.click();
    });
    expect(heading()).toBe('Devices & sign-in');
    expect(menu()).toEqual([]);
    expect(box()).toBeNull(); // only above the two steps' own sections on a phone
    await act(async () => {
      link('‹ Settings')!.click();
    });
    expect(heading()).toBeNull();

    await open('/connect/email');
    expect(box()).not.toBeNull();
  });
});

describe('useSetupOnFocus', () => {
  function Watch() {
    useSetupOnFocus();
    return null;
  }

  it('asks for the email again on focus while the AI step is still open', async () => {
    resetSession();
    api.getSession.mockResolvedValue({ ...SESSION, email: 'me@example.com' });
    api.getAiTools.mockResolvedValue([]);
    await act(async () => {
      await bootstrap();
    });
    await act(async () => {
      root.render(<Watch />);
    });
    api.getSession.mockClear();
    api.getSession.mockResolvedValue({ ...SESSION, email: 'me@example.com', verified: true });
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });
    expect(api.getAiTools).toHaveBeenCalledTimes(1);
    expect(api.getSession).toHaveBeenCalledTimes(1);
  });
});
