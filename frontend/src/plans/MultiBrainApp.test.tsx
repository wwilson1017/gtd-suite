// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
vi.mock('../core/app', async (original) => ({
  ...(await original<typeof import('../core/app')>()),
  APP: 'brain',
  APP_TITLE: 'Common Brain',
}));
import { initializeBrains } from '../apps/todo-gtd/brainSelection';
import { BrainApp } from '../apps/brain/BrainApp';
import { resetSession } from '../apps/todo-gtd/session';

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
it('says the brain limit is reached from New brain', async () => {
  cap = 1;
  available = [brains[0]];
  await mount();
  await act(async () => (host.querySelector('[aria-label="Switch brain"]') as HTMLButtonElement).click());
  await click('New brain');
  expect(host.textContent).toContain('Your account has reached its brain limit.');
  expect(host.querySelector('input[aria-label="Brain name"]')).toBeNull();
});
