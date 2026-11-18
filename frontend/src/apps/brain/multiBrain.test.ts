// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { initializeBrains, selectedBrain, selectBrain } from '../todo-gtd/brainSelection';
import {
  getOverview,
  getArchive,
  getChanges,
  getMemory,
  getPage,
  getHistory,
  getFiles,
  searchBrain,
  updateMemory,
  importMarkdown,
  download,
} from './api';
const brains = [
  { id: 11, name: 'Personal', folder: 'personal', status: 'active' as const },
  { id: 22, name: 'Work', folder: 'work', status: 'active' as const },
];
beforeEach(() => {
  localStorage.clear();
  initializeBrains(7, brains);
  selectBrain(11);
});
afterEach(() => vi.unstubAllGlobals());
it('scopes every content read, import and download to the selected brain', async () => {
  const mock = vi.fn(async (url: string, init: RequestInit) => {
    expect(new Headers(init.headers).get('X-Brain')).toBe('22');
    if (url.includes('/export')) return new Response('zip');
    return Response.json({ marker: 'Work', changes: ['Work'], versions: ['Work'] });
  });
  vi.stubGlobal('fetch', mock);
  selectBrain(22);
  const reads = await Promise.all([
    getOverview(),
    getArchive(),
    getChanges(),
    getMemory(1),
    getPage(2),
    getHistory('page', 2),
    getFiles(),
    searchBrain('work'),
  ]);
  expect(reads.every((r) => JSON.stringify(r).includes('Work'))).toBe(true);
  await importMarkdown(new File(['zip'], 'work.zip'), true, false);
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL() {
        return 'blob:test';
      }
      static revokeObjectURL() {}
    },
  );
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await download('/export', 'brain.zip');
  expect(click).toHaveBeenCalledOnce();
  click.mockRestore();
  expect(mock).toHaveBeenCalledTimes(10);
});
it('rejects late old-brain data even if the person switched away and back', async () => {
  let finish!: (r: Response) => void;
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const result = getOverview();
  selectBrain(22);
  selectBrain(11);
  finish(Response.json({ memories: ['old'] }));
  await expect(result).rejects.toThrow('selected brain changed');
});
it('falls back after brain_gone without repeating a mutation', async () => {
  selectBrain(22);
  const mock = vi.fn(async (url: string) =>
    url === '/api/app/brains'
      ? Response.json({ brains: [brains[0]], caps: {}, link_brains: [11] })
      : Response.json({ detail: { brain_gone: true } }, { status: 409 }),
  );
  vi.stubGlobal('fetch', mock);
  await expect(updateMemory(2, { text: 'Changed' })).rejects.toThrow();
  expect(selectedBrain()).toBe(11);
  expect(mock.mock.calls.map(([url]) => url)).toEqual(['/api/app/brain/memories/2', '/api/app/brains']);
});
it('remembers the selection per account, honours brain links, and tolerates disabled storage', () => {
  selectBrain(22);
  initializeBrains(8, [{ ...brains[0], id: 33 }]);
  initializeBrains(7, brains);
  expect(selectedBrain()).toBe(22);
  window.history.replaceState({}, '', '/app?brain=11');
  initializeBrains(9, brains);
  expect(selectedBrain()).toBe(11);
  expect(localStorage.getItem('brain:9')).toBe('11');
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('disabled');
  });
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('disabled');
  });
  expect(() => {
    initializeBrains(10, brains);
    selectBrain(22);
  }).not.toThrow();
  get.mockRestore();
  set.mockRestore();
  window.history.replaceState({}, '', '/app');
});
