// @vitest-environment jsdom
//
// The boot path on Notes GTD's address: the server names the app in the gtd-app
// meta (backend/pages.py), and Root mounts the notes app on /app, after the session
// call has named the list, with every notes request carrying X-List.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stubNavigation } from '../todo-gtd/stubNavigation';

const SESSION = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: false,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['notes'],
};
const NOTE = {
  id: 1,
  title: 'Packing',
  body: '- [ ] tent #trip',
  tags: ['trip'],
  color: 'teal',
  pinned: true,
  status: 'active',
  version: 2,
  source: 'agent',
  source_client: 'Claude',
  edited_by: 'Claude',
  created_at: '2026-10-12T00:00:00Z',
  updated_at: '2026-10-12T00:00:00Z',
};

function answer(path: string): { status: number; body: unknown } {
  if (path === '/api/app/session') return { status: 200, body: SESSION };
  if (path === '/api/app/notes') return { status: 200, body: { notes: [NOTE], count: 1, next_offset: null } };
  if (path === '/api/app/notes/tags') return { status: 200, body: { tags: [{ tag: 'trip', count: 1 }] } };
  return { status: 404, body: { detail: 'Not found' } };
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot> | null = null;
let fetchMock: ReturnType<typeof vi.fn>;
let meta: HTMLMetaElement;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  meta = document.createElement('meta');
  meta.name = 'gtd-app';
  meta.content = 'notes';
  document.head.appendChild(meta);
  fetchMock = vi.fn(async (url: string) => {
    const { status, body } = answer(String(url).split('?')[0]);
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  stubNavigation();
  window.history.replaceState({}, '', '/app');
  host = document.createElement('div');
  document.body.appendChild(host);
});

afterEach(async () => {
  if (root) {
    const r = root;
    root = null;
    await act(async () => {
      r.unmount();
    });
  }
  host.remove();
  meta.remove();
  vi.unstubAllGlobals();
  vi.resetModules();
});

/** Every lazy boundary on the path committed: wait for `text` on screen. */
async function settle(text: string) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    if (host.textContent?.includes(text)) return;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
  throw new Error(`never showed ${text}; showed ${JSON.stringify(host.textContent)}`);
}

describe('Root on Notes GTD', () => {
  it('mounts the notes app on /app, with the list named on every notes request', async () => {
    const { default: Root } = await import('../../Root');
    root = createRoot(host);
    await act(async () => {
      root!.render(<Root />);
    });
    await settle('Packing');

    expect(host.textContent).toContain('Notes GTD');
    expect(host.textContent).toContain('Take a note…');
    expect(host.textContent).toContain('edited by Claude');
    expect(host.querySelector('input[type=checkbox]')).not.toBeNull();
    expect(document.title).toBe('Notes');
    const calls = fetchMock.mock.calls.map(([url, init]) => ({
      path: String(url).split('?')[0],
      xList: ((init as RequestInit | undefined)?.headers as Record<string, string> | undefined)?.['X-List'],
    }));
    expect(calls[0]).toEqual({ path: '/api/app/session', xList: undefined });
    expect(calls.filter((c) => c.path.startsWith('/api/app/notes')).every((c) => c.xList === '7')).toBe(true);
  }, 30_000);
});
