// @vitest-environment jsdom
//
// The Sites home page: the account's pages and short links with their caps, the
// new-page form (pasted or from a file), taking one down, deleting after a confirm,
// and short links held back while their cap is 0.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../apps/todo-gtd/types';
import type { Site, SiteCaps } from '../apps/sites/types';

// Pro is not on sale here.
const todoApi = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(async () => ({ billing: false })),
}));
vi.mock('../apps/todo-gtd/api', () => todoApi);
const api = vi.hoisted(() => ({
  readSiteData: vi.fn(),
  clearSiteData: vi.fn(),
  listSites: vi.fn(),
  createPage: vi.fn(),
  createLink: vi.fn(),
  updateSite: vi.fn(),
  deleteSite: vi.fn(),
}));
vi.mock('../apps/sites/api', () => api);

import { bootstrap, resetSession } from '../apps/todo-gtd/session';
import { SitesPage } from '../apps/sites/SitesPage';

const SESSION: Session = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['sites'],
};
const PAGE: Site = {
  id: 3,
  kind: 'page',
  code: 'k7Qm2xPa9R',
  name: 'menu',
  title: 'Lunch menu',
  format: 'markdown',
  bytes: 2048,
  status: 'published',
  address: 'https://sites.example/menu-k7Qm2xPa9R',
  source: 'agent',
  source_client: 'Claude',
  created_at: '2026-10-12T15:00:00.000Z',
  updated_at: '2026-10-12T15:00:00.000Z',
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function show(session: Partial<Session> = {}, sites: Site[] = [PAGE], caps: SiteCaps = { pages: 5, links: 0 }) {
  resetSession();
  todoApi.getSession.mockResolvedValue({ ...SESSION, ...session });
  await act(async () => {
    await bootstrap();
  });
  api.listSites.mockResolvedValue({ sites, caps });
  await act(async () => {
    root.render(
      <MemoryRouter>
        <SitesPage />
      </MemoryRouter>,
    );
  });
}

const button = (label: string) => {
  const found = [...host.querySelectorAll('button')].find((b) => b.textContent === label);
  if (!found) throw new Error(`no "${label}" button in ${JSON.stringify(host.textContent)}`);
  return found;
};

function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

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
  vi.unstubAllGlobals();
});

describe('Sites', () => {
  it('locks a page with a password on Pro, and takes a lock off', async () => {
    await show();
    expect([...host.querySelectorAll('button')].some((b) => b.textContent === 'Lock with a password')).toBe(false); // free: no lock
    await act(async () => {
      root.unmount();
    });
    root = createRoot(host);
    const pro = { pro: true, status: 'active', until: '2027-01-01T00:00:00Z', cancels: false, manageable: true };
    await show({ plan: pro });
    api.updateSite.mockResolvedValue({ ...PAGE, locked: true });
    await act(async () => {
      button('Lock with a password').click();
    });
    const field = host.querySelector<HTMLInputElement>('input[aria-label="Password for this page"]')!;
    expect(field.type).toBe('password'); // masked: never shown on screen
    type(field, 'open sesame');
    await act(async () => {
      button('Save').click();
    });
    expect(api.updateSite).toHaveBeenCalledWith(PAGE.id, { password: 'open sesame' });
    await act(async () => {
      root.unmount();
    });
    root = createRoot(host);
    await show({ plan: pro }, [{ ...PAGE, locked: true }]);
    expect(host.textContent).toContain('🔒 Password');
    await act(async () => {
      button('Remove password').click();
    });
    expect(api.updateSite).toHaveBeenLastCalledWith(PAGE.id, { password: '' });
  });

  it('keeps the typed password when the save fails', async () => {
    const pro = { pro: true, status: 'active', until: '2027-01-01T00:00:00Z', cancels: false, manageable: true };
    await show({ plan: pro });
    api.updateSite.mockRejectedValue(new Error('busy'));
    await act(async () => {
      button('Lock with a password').click();
    });
    const field = host.querySelector<HTMLInputElement>('input[aria-label="Password for this page"]')!;
    type(field, 'open sesame');
    await act(async () => {
      button('Save').click();
    });
    const still = host.querySelector<HTMLInputElement>('input[aria-label="Password for this page"]');
    expect(still?.value).toBe('open sesame');
  });

  it('shows views where the server sends them (Pro), and nothing where it does not', async () => {
    await show();
    expect(host.textContent).not.toMatch(/\bviews?\b/);
    await act(async () => {
      root.unmount();
    });
    root = createRoot(host);
    await show({}, [{ ...PAGE, views: 3 }]);
    expect(host.textContent).toContain('3 views');
  });

  it('takes the bigger page size the plan allows (Max: 10 MB)', async () => {
    await show({}, [], { pages: 10_000, links: 10_000, page_bytes: 10_000_000 });
    const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
    const big = new File(['x'], 'deck.html');
    Object.defineProperty(big, 'size', { value: 9_000_000 });
    const text = vi.spyOn(big, 'text');
    Object.defineProperty(input, 'files', { value: [big] });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(text).toHaveBeenCalled();
    expect(host.querySelector('[role=alert]')).toBeNull();
  });
  it('lets a self-host without a plan lock pages and see view counts', async () => {
    await show({ hosted: false }, [{ ...PAGE, views: 3 }]);
    expect(host.textContent).toContain('3 views');
    await act(async () => {
      button('Lock with a password').click();
    });
    expect(host.querySelector<HTMLInputElement>('input[aria-label="Password for this page"]')?.type).toBe('password');
  });
});
