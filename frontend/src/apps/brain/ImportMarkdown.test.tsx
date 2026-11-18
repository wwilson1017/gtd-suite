// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ importMarkdown: vi.fn(), getChanges: vi.fn() }));
vi.mock('./api', () => api);
vi.mock('./BrainShell', () => ({ BrainShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock('react-router-dom', () => ({ Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span> }));
import { ImportMarkdown } from './ImportMarkdown';
import { ChangesPage } from './ChangesPage';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const button = (text: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === text)!;
const report = {
  complete: true,
  processed: 0,
  written: 0,
  skipped: 0,
  archived: 0,
  counts: { pages: 2, memories: 1, files: 1 },
  path_changes: [{ from: 'People/Maya.md', to: 'people/maya' }],
  removed: [{ path: 'People/Maya.md', counts: [{ kind: 'password', count: 1 }] }],
  oversized: ['big.md'],
  decoded: ['bad.md'],
  warnings: [],
  over_cap: ['pages'],
  error: null,
  entries: [{ kind: 'file', path: 'image.png', planned: 'files are off', result: 'pending' }],
};
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it('previews before import, shows details and failure progress, and clears a changed file', async () => {
  api.importMarkdown.mockResolvedValue(report);
  await act(async () => root.render(<ImportMarkdown />));
  expect(button('Import')).toBeUndefined();
  const input = host.querySelector('input[type=file]')!;
  const file = new File(['zip'], 'notes.zip');
  await act(async () => {
    Object.defineProperty(input, 'files', { configurable: true, value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await act(async () => button('Preview import').click());
  expect(api.importMarkdown).toHaveBeenCalledWith(file, true, false);
  for (const text of [
    '2 pages, 1 memories, 1 files',
    'People/Maya.md → people/maya',
    'blanked 1 password',
    'oversized page becomes a file',
    'files are off',
    'Over the current cap: pages',
  ])
    expect(host.textContent).toContain(text);
  await act(async () => (host.querySelector('input[type=checkbox]') as HTMLInputElement).click());
  api.importMarkdown.mockResolvedValue({ ...report, complete: false, processed: 1, written: 1, error: 'Cap reached.' });
  await act(async () => button('Import').click());
  expect(api.importMarkdown).toHaveBeenLastCalledWith(file, false, true);
  expect(host.textContent).toContain('Import stopped. 1 processed');
  expect(host.textContent).toContain('Run it again to resume.');
  expect(button('Import')).toBeUndefined();
  await act(async () => {
    Object.defineProperty(input, 'files', { configurable: true, value: [new File(['zip'], 'other.zip')] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  expect(host.textContent).not.toContain('Cap reached.');
});

it('groups consecutive versions under a pass and reason without merging separated passes', async () => {
  const change = { kind: 'page', version: 1, action: 'added', by: 'you', at: '2026-10-31T12:00:00Z', what: 'A page' };
  api.getChanges.mockResolvedValue([
    { ...change, item_id: 1, pass: 'Import one', reason: 'Import Markdown' },
    { ...change, item_id: 2, pass: 'Import one', reason: 'Import Markdown' },
    { ...change, item_id: 3, pass: '', reason: '' },
    { ...change, item_id: 4, pass: 'Import one', reason: 'Import Markdown' },
  ]);
  await act(async () => root.render(<ChangesPage />));
  const sections = [...host.querySelectorAll('section')];
  expect(sections).toHaveLength(3);
  expect(sections.map((s) => s.querySelectorAll('li').length)).toEqual([2, 1, 1]);
  expect(sections[0].querySelector('h2')?.textContent).toBe('Import one');
  expect(sections[0].textContent).toContain('Import Markdown');
});
