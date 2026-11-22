// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
vi.mock('../../core/app', async (original) => ({
  ...(await original<typeof import('../../core/app')>()),
  APP: 'brain',
  APP_TITLE: 'Common Brain',
}));
import { initializeBrains } from '../todo-gtd/brainSelection';
import { BrainApp } from './BrainApp';
import { resetSession } from '../todo-gtd/session';

const AT = '2026-11-15T12:00:00Z';
const brains = [11, 22].map((id) => ({
  id,
  name: id === 11 ? 'Personal' : 'Work',
  folder: id === 11 ? 'personal' : 'work',
  status: 'active',
  description: '',
  rules: [],
  ai_access: 'write',
  settled_at: AT,
}));
const memory = (brain: string) => ({
  id: 1,
  text: `${brain} memory`,
  locked: false,
  status: 'active',
  version: 1,
  created_by: 'you',
  updated_by: 'you',
  created_at: AT,
  updated_at: AT,
});
const page = (brain: string) => ({
  ...memory(brain),
  id: 3,
  path: 'notes/page',
  title: `${brain} page`,
  body: `${brain} body`,
  format: 'markdown',
  size: 10,
});
const overview = (brain: string) => ({
  memories: [memory(brain)],
  pages: [page(brain)],
  folders: [],
  ais: [],
  caps: { ais: 3, memories: 50, pages: 50 },
  nudge: false,
  custom_instruction: 'Use my brain',
});
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let fetchMock: ReturnType<typeof vi.fn>;
let cap: number;
let available: typeof brains;
const json = (body: unknown) => Response.json(body);
function answer(url: string, init: RequestInit = {}) {
  const brain = new Headers(init.headers).get('X-Brain') === '22' ? 'Work' : 'Personal';
  const path = url.split('?')[0];
  if (path === '/api/app/session')
    return json({
      list_id: 7,
      state: 'active',
      email: null,
      verified: false,
      hosted: true,
      mail: false,
      apps: ['brain'],
      brains: available,
      caps: { brains: cap },
    });
  if (path === '/api/config') return json({ app: 'brain', apps: {} });
  if (path === '/api/app/brains')
    return json({ brains: available, caps: { brains: cap, links: 3, raisable: cap === 1 }, link_brains: [11] });
  if (path === '/api/app/brains/11') return json({ ...brains[0], ...JSON.parse(init.body as string) });
  if (path === '/api/app/brain') return json(overview(brain));
  if (path === '/api/app/brain/pages/3') return json(page(brain));
  if (path === '/api/app/brain/search')
    return json({ memories: [{ ...memory(brain), text: `${brain} search` }], pages: [] });
  if (path === '/api/app/brain/archive')
    return json({ memories: [{ ...memory(brain), text: `${brain} archive` }], pages: [] });
  if (path === '/api/app/brain/history/page/3')
    return json({
      versions: [{ ...page(brain), version: 1, by: 'you', at: AT, action: 'created', body: `${brain} history` }],
    });
  if (path === '/api/app/brain/files')
    return json({
      on: true,
      used: 1,
      quota: 1000,
      files: [{ id: 9, path: `${brain}.txt`, size: 1, status: 'active', created_by: 'you', updated_at: AT }],
    });
  return json({});
}
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  resetSession();
  localStorage.clear();
  initializeBrains(0, []);
  cap = 10;
  available = brains;
  window.history.replaceState({}, '', '/app');
  fetchMock = vi.fn(async (url: string, init: RequestInit) => answer(url, init));
  vi.stubGlobal('fetch', fetchMock);
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function mount() {
  await act(async () => root.render(<BrainApp />));
}
async function click(text: string) {
  const el = [...host.querySelectorAll('button,a')].find((e) => e.textContent?.trim() === text) as HTMLElement;
  expect(el, `Missing ${text}`).toBeTruthy();
  await act(async () => el.click());
}
async function type(selector: string, text: string) {
  const el = host.querySelector(selector) as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, text);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function wait(text: string) {
  for (let i = 0; i < 100; i++) {
    if (host.textContent?.includes(text)) return;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
  expect(host.textContent).toContain(text);
}
async function switchWork() {
  await act(async () => (host.querySelector('[aria-label="Switch brain"]') as HTMLButtonElement).click());
  await click('Work');
}

it('switches all read views, remounts search and page state, and sends the second brain header', async () => {
  await mount();
  expect(host.textContent).toContain('Personal memory');
  await switchWork();
  expect(host.textContent).toContain('Work memory');
  expect(host.textContent).not.toContain('Personal memory');
  await type('[aria-label="Search your brain"]', 'anything');
  await wait('Work search');
  await type('[aria-label="Search your brain"]', '');
  await act(async () => (host.querySelector('a[href="/app/p/3"]') as HTMLAnchorElement).click());
  await wait('Work body');
  await click('History');
  await wait('Work history');
  await click('Close');
  await click('Archive');
  await wait('Work archive');
  await click('Files');
  await wait('Work.txt');
  for (const sub of [
    '/brain',
    '/brain/search',
    '/brain/pages/3',
    '/brain/history/page/3',
    '/brain/archive',
    '/brain/files',
  ]) {
    const calls = fetchMock.mock.calls.filter(([url]) => String(url).split('?')[0] === `/api/app${sub}`);
    expect(new Headers(calls.at(-1)![1].headers).get('X-Brain')).toBe('22');
  }
});
it('never renders an old overview that arrives after switching', async () => {
  let finish!: (r: Response) => void;
  fetchMock.mockImplementation((url: string, init: RequestInit) =>
    url === '/api/app/brain' && new Headers(init.headers).get('X-Brain') === '11'
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : Promise.resolve(answer(url, init)),
  );
  await mount();
  await switchWork();
  await act(async () => finish(json(overview('Personal'))));
  expect(host.textContent).toContain('Work memory');
  expect(host.textContent).not.toContain('Personal memory');
});
it('saves rule chips and editable rules through the shared settings form', async () => {
  window.history.replaceState({}, '', '/app/brains');
  await mount();
  await click('Work only');
  await click('+ Add a rule');
  await click('Write a rule');
  const input = host.querySelector('textarea[aria-label="Rule 2"]') as HTMLTextAreaElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(
      input,
      'Keep private details out',
    );
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => input.dispatchEvent(new FocusEvent('focusout', { bubbles: true })));
  const writes = fetchMock.mock.calls.filter(([url, init]) => url === '/api/app/brains/11' && init.method === 'PUT');
  expect(JSON.parse(writes.at(-1)![1].body).rules).toEqual([
    'Work only: no personal life, family, health or money.',
    'Keep private details out',
  ]);
});
it('opens a brain from a link and falls back visibly when it is gone', async () => {
  window.history.replaceState({}, '', '/app?brain=22');
  // A fresh account bootstrap exercises the external-link selection.
  fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
    if (url === '/api/app/session') {
      const res = await answer(url, init).json();
      return json({ ...res, list_id: 90 });
    }
    if (url === '/api/app/brain' && new Headers(init.headers).get('X-Brain') === '22') {
      available = [brains[0]];
      return Response.json({ detail: { brain_gone: true } }, { status: 409 });
    }
    return answer(url, init);
  });
  await mount();
  await wait('Personal memory');
  expect(host.textContent).toContain('That brain is no longer available');
  await click('Files');
  await wait('Personal.txt');
  expect(window.location.pathname).toBe('/app/files');
});

it('labels an unnamed brain without settling its name for the AI', async () => {
  available = [brains[0], { ...brains[1], name: '' }];
  await mount();
  await act(async () => (host.querySelector('[aria-label="Switch brain"]') as HTMLButtonElement).click());
  await click('Brain 2');
  expect(host.querySelector('[aria-label="Switch brain"]')!.textContent).toContain('Brain 2');
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false);
});
it('keeps the old addresses landing in Settings, with the Common Brain group in its menu', async () => {
  window.history.replaceState({}, '', '/app/brains');
  await mount();
  await wait('Editing Personal');
  expect(window.location.pathname).toBe('/app/connect/brains');
  const menu = [...host.querySelectorAll('nav[aria-label="Settings"] a')].map((a) => a.getAttribute('href'));
  // mail: false, so no email step; no level is shown while the suite is free.
  expect(menu).toEqual(
    ['ai', 'devices', 'install', 'brains', 'every', 'curator', 'export', 'keys'].map((k) => `/app/connect/${k}`),
  );
  expect(host.querySelector('a[aria-label="Settings"][aria-current="page"]')).not.toBeNull();
  expect([...host.querySelectorAll('header nav a')].map((a) => a.textContent)).toEqual([
    'Brain',
    'Files',
    'Changes',
    'Archive',
  ]);
  await act(async () => root.unmount());
  root = createRoot(host);
  window.history.replaceState({}, '', '/app/brains/new');
  await mount();
  await wait('Create brain');
  expect(window.location.pathname + window.location.search).toBe('/app/connect/brains?new');
  await act(async () => root.unmount());
  root = createRoot(host);
  window.history.replaceState({}, '', '/app/connect?brain=22#export');
  await mount();
  await wait('Download my brain (.zip)');
  expect(window.location.pathname + window.location.search).toBe('/app/connect/export?brain=22');
});
