// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => {
  document.head.innerHTML = '';
  vi.unstubAllGlobals();
  vi.resetModules();
});

it('defaults to Todo and an empty base on an existing host', async () => {
  vi.resetModules();
  const app = await import('./app');
  expect(app.APP).toBe('todo');
  expect(app.BASE).toBe('');
});

it.each(['notes', 'projects', 'sites', 'brain'])('uses the server base for %s routes and API calls', async (key) => {
  document.head.innerHTML = `<meta name="gtd-app" content="${key}"><meta name="gtd-base" content="/${key}">`;
  window.history.replaceState(null, '', `/${key}/app/connect`);
  vi.resetModules();
  const app = await import('./app');
  const mode = await import('../apps/todo-gtd/publicMode');
  expect(app.APP).toBe(key);
  expect(app.BASE).toBe(`/${key}`);
  expect(mode.TODO_PUBLIC_BASE).toBe(`/${key}/app`);
  expect(mode.TODO_API_BASE).toBe(`/${key}/api/app`);
  const fetcher = vi.fn(async () => new Response('{}', { status: 200 }));
  vi.stubGlobal('fetch', fetcher);
  const api = await import('../apps/todo-gtd/api');
  await api.getConfig();
  await api.todoFetch('/session');
  await api.redeemSignIn('TOKEN');
  expect(fetcher.mock.calls.map((call) => (call as unknown[])[0])).toEqual([
    `/${key}/api/config`,
    `/${key}/api/app/session`,
    `/${key}/api/signin/TOKEN`,
  ]);
});
