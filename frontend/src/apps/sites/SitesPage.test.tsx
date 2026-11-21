// @vitest-environment jsdom
//
// The Sites home page: the account's pages and short links with their caps, the
// new-page form (pasted or from a file), taking one down, deleting after a confirm,
// and short links held back while their cap is 0.
import { act } from 'react';
import { NO_PAID_OFFERS } from '../../paid/features';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../todo-gtd/types';
import type { Site, SiteCaps } from './types';

// The account card asks what the server offers.
const todoApi = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(async () => ({ ...NO_PAID_OFFERS })),
}));
vi.mock('../todo-gtd/api', () => todoApi);
const api = vi.hoisted(() => ({
  readSiteData: vi.fn(),
  clearSiteData: vi.fn(),
  listSites: vi.fn(),
  createPage: vi.fn(),
  createLink: vi.fn(),
  updateSite: vi.fn(),
  deleteSite: vi.fn(),
}));
vi.mock('./api', () => api);

import { bootstrap, resetSession } from '../todo-gtd/session';
import { SitesPage } from './SitesPage';

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
  it('shows when an unconfirmed site comes down and links to email confirmation', async () => {
    const now = Date.parse('2026-11-15T12:00:00Z');
    const clock = vi.spyOn(Date, 'now').mockReturnValue(now);
    try {
      await show({}, [{ ...PAGE, expires_at: '2026-11-22T12:00:00Z' }]);
      expect(host.textContent).toContain('Comes down in 7 days');
      expect(
        [...host.querySelectorAll('a')].some(
          (a) => a.getAttribute('href') === '/app/connect/email' && a.textContent === 'confirm your email',
        ),
      ).toBe(true);
    } finally {
      clock.mockRestore();
    }
  });

  it('sends an optional short name from the new-link form', async () => {
    await show({ verified: true }, [], { pages: 500, links: 500 });
    api.createLink.mockResolvedValue({
      ...PAGE,
      kind: 'link',
      short_name: 'vancouver',
      address: 'https://ss.example/vancouver',
    });
    await act(async () => {
      type(host.querySelector<HTMLInputElement>('input[type=url]')!, 'https://example.com');
      type(host.querySelector<HTMLInputElement>('input[placeholder=vancouver]')!, 'vancouver');
    });
    await act(async () => {
      button('Make a short link').click();
    });
    expect(api.createLink).toHaveBeenCalledWith({
      url: 'https://example.com',
      name: undefined,
      short_name: 'vancouver',
    });
    expect(host.querySelector('[role=status]')?.textContent).toContain('https://ss.example/vancouver');
  });

  it('sets the data mode with the shared exposure warning, reads and clears records', async () => {
    await show({}, [{ ...PAGE, data: 'collect', records: 2 }]);
    api.updateSite.mockResolvedValue({ ...PAGE, data: 'shared' });
    await act(async () => {
      button('Data collect · 2 records').click();
    });
    expect(host.textContent).toContain('including visitor records sent while Collect was on');
    const select = host.querySelector<HTMLSelectElement>('select[aria-label="Data mode"]')!;
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    );
    const change = async (value: string) =>
      act(async () => {
        select.value = value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      });
    await change('shared');
    expect(api.updateSite).not.toHaveBeenCalled();
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    );
    await change('shared');
    expect(api.updateSite).toHaveBeenLastCalledWith(PAGE.id, { data: 'shared' });
    await change('off');
    expect(api.updateSite).toHaveBeenLastCalledWith(PAGE.id, { data: 'off' });
    const newest = { id: 9, by: 'visitor', at: '2026-11-10T12:00:00Z', data: { answer: '<script>private</script>' } };
    const oldest = { id: 7, by: 'owner', at: '2026-11-09T12:00:00Z', data: { ack: true } };
    api.readSiteData
      .mockResolvedValueOnce({ records: [newest], next: 9, more: true })
      .mockResolvedValueOnce({ records: [oldest], next: 7, more: false });
    await act(async () => {
      button('Records').click();
    });
    expect(host.querySelector('pre')?.textContent).toBe(JSON.stringify(newest.data, null, 2));
    expect(host.querySelector('li script')).toBeNull();
    await act(async () => {
      button('Older records').click();
    });
    expect(api.readSiteData).toHaveBeenLastCalledWith(PAGE.id, 9);
    expect([...host.querySelectorAll('pre')].map((p) => p.textContent)).toEqual([
      JSON.stringify(newest.data, null, 2),
      JSON.stringify(oldest.data, null, 2),
    ]);
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    );
    await act(async () => {
      button('Clear all').click();
    });
    expect(api.clearSiteData).not.toHaveBeenCalled();
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    );
    api.clearSiteData.mockResolvedValue(undefined);
    await act(async () => {
      button('Clear all').click();
    });
    expect(api.clearSiteData).toHaveBeenCalledWith(PAGE.id);
    expect(host.querySelectorAll('pre').length).toBe(0);
    expect(host.textContent).toContain('No records yet.');
  });

  it('downloads every page of data using the before cursor', async () => {
    await show({}, [{ ...PAGE, records: 2 }]);
    const newest = { id: 8, by: 'visitor', at: 'now', data: { answer: 'yes' } };
    const oldest = { id: 2, by: 'owner', at: 'then', data: { ack: true } };
    api.readSiteData
      .mockResolvedValueOnce({ records: [newest], next: 8, more: true })
      .mockResolvedValueOnce({ records: [oldest], next: 2, more: false });
    const makeUrl = vi.fn<(blob: Blob) => string>(() => 'blob:download');
    vi.stubGlobal('URL', { createObjectURL: makeUrl, revokeObjectURL: vi.fn() });
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await act(async () => {
      button('Data off · 2 records').click();
    });
    await act(async () => {
      button('Download JSON').click();
    });
    expect(api.readSiteData).toHaveBeenNthCalledWith(1, PAGE.id, undefined);
    expect(api.readSiteData).toHaveBeenNthCalledWith(2, PAGE.id, 8);
    expect(JSON.parse(await makeUrl.mock.calls[0][0].text())).toEqual([newest, oldest]);
    expect(clicked).toHaveBeenCalledOnce();
    clicked.mockRestore();
  });

  it('lists the pages with their addresses and the caps', async () => {
    await show();
    expect(host.textContent).toContain('Lunch menu');
    expect(host.textContent).toContain('1 of 5');
    expect(host.textContent).toContain('No short links yet.');
    expect(host.textContent).not.toContain('0 of 0'); // no links until the email is confirmed
    const a = host.querySelector<HTMLAnchorElement>('a[href="https://sites.example/menu-k7Qm2xPa9R"]')!;
    expect(a.target).toBe('_blank');
    expect(a.rel).toContain('noopener');
  });

  it('files a page and finds it by folder and by words', async () => {
    const filed = { ...PAGE, id: 9, title: 'Board pack', note: 'For Dana, Hauptstraße', folder: 'Board' };
    await show({}, [PAGE, filed]);
    expect(host.textContent).toContain('📁 Board');
    expect(host.textContent).toContain('For Dana');
    const search = host.querySelector<HTMLInputElement>('input[type=search]')!;
    type(search, 'dana');
    expect(host.textContent).toContain('Board pack');
    expect(host.textContent).not.toContain('Lunch menu');
    type(search, 'HAUPTSTRASSE'); // full case folding, as the server's
    expect(host.textContent).toContain('Board pack');
    type(search, 'HAUPTSTRAẞE'); // the capital sharp s folds to ss too
    expect(host.textContent).toContain('Board pack');
    expect(host.textContent).not.toContain('Lunch menu');
    expect(host.textContent).not.toContain('Lunch menu');
    type(search, '');
    const select = host.querySelector<HTMLSelectElement>('select[aria-label=Folder]')!;
    await act(async () => {
      select.value = '';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(host.textContent).toContain('Lunch menu');
    expect(host.textContent).not.toContain('Board pack');
    api.updateSite.mockResolvedValue({ ...PAGE, folder: 'Office' });
    await act(async () => {
      button('Note & folder').click();
    });
    const folderField = host.querySelector<HTMLInputElement>('li form input[list=site-folders]')!;
    type(folderField, 'Office');
    await act(async () => {
      button('Save').click();
    });
    expect(api.updateSite).toHaveBeenCalledWith(PAGE.id, { note: '', folder: 'Office' });
  });

  it('publishes a pasted page and shows its address', async () => {
    await show({}, []);
    api.createPage.mockResolvedValue(PAGE);
    type(host.querySelector('textarea')!, '# Lunch menu');
    type(host.querySelector<HTMLInputElement>('input[placeholder="menu"]')!, 'Menu');
    await act(async () => {
      button('Publish').click();
    });
    expect(api.createPage).toHaveBeenCalledWith({ content: '# Lunch menu', format: 'markdown', name: 'menu' });
    expect(host.querySelector('[role=status]')?.textContent).toContain(PAGE.address);
    expect(api.listSites).toHaveBeenCalledTimes(2);
  });

  it('ignores an older list load that fails after a newer one answered', async () => {
    resetSession();
    todoApi.getSession.mockResolvedValue(SESSION);
    await act(async () => {
      await bootstrap();
    });
    let failFirst: (e: Error) => void = () => {};
    api.listSites
      .mockReturnValueOnce(
        new Promise((_, reject) => {
          failFirst = reject;
        }),
      )
      .mockResolvedValue({ sites: [PAGE], caps: { pages: 5, links: 0 } });
    await act(async () => {
      root.render(
        <MemoryRouter>
          <SitesPage />
        </MemoryRouter>,
      );
    });
    api.createPage.mockResolvedValue(PAGE);
    type(host.querySelector('textarea')!, '# Lunch menu');
    await act(async () => {
      button('Publish').click();
    });
    expect(host.textContent).toContain('Lunch menu');
    await act(async () => {
      failFirst(new Error('network'));
    });
    expect(host.querySelector('[role=alert]')).toBeNull();
  });

  it('drops the "published" note once that page is taken down', async () => {
    await show();
    api.createPage.mockResolvedValue(PAGE);
    type(host.querySelector('textarea')!, '# Lunch menu');
    await act(async () => {
      button('Publish').click();
    });
    expect(host.querySelector('[role=status]')).not.toBeNull();
    api.updateSite.mockResolvedValue({ ...PAGE, status: 'unpublished' });
    await act(async () => {
      button('Take down').click();
    });
    expect(host.querySelector('[role=status]')).toBeNull();
  });

  it('refuses a file over 2 MB without reading it', async () => {
    await show({}, []);
    const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
    const big = new File(['x'], 'huge.md');
    Object.defineProperty(big, 'size', { value: 2_000_001 });
    const text = vi.spyOn(big, 'text');
    Object.defineProperty(input, 'files', { value: [big] });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(text).not.toHaveBeenCalled();
    expect(host.querySelector('[role=alert]')?.textContent).toBe('A page is at most 2 MB.');
  });

  it('takes a page from a file, as HTML when the file is', async () => {
    await show({}, []);
    const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
    const file = new File(['<p>Hi</p>'], 'menu.html', { type: 'text/html' });
    Object.defineProperty(input, 'files', { value: [file] });
    // Cleared once taken, so picking the same file again fires a change.
    const valueSet = vi.fn();
    Object.defineProperty(input, 'value', { set: valueSet, get: () => '' });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(host.querySelector('textarea')!.value).toBe('<p>Hi</p>');
    expect(host.querySelector<HTMLSelectElement>('form select')!.value).toBe('html');
    expect(valueSet).toHaveBeenCalledWith('');
  });

  it('holds the form while a file is read, so the old text cannot be published', async () => {
    await show({}, []);
    type(host.querySelector('textarea')!, '# Old');
    const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
    let finish: (text: string) => void = () => {};
    const slow = new File(['<p>New</p>'], 'new.html');
    vi.spyOn(slow, 'text').mockReturnValue(
      new Promise((r) => {
        finish = r;
      }),
    );
    Object.defineProperty(input, 'files', { value: [slow] });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(button('Publish').matches(':disabled')).toBe(true);
    expect(host.querySelector('textarea')!.matches(':disabled')).toBe(true);
    await act(async () => {
      finish('<p>New</p>');
    });
    expect(button('Publish').matches(':disabled')).toBe(false);
    expect(host.querySelector('textarea')!.value).toBe('<p>New</p>');
  });

  it('takes a page down, and deletes only after a yes', async () => {
    await show();
    api.updateSite.mockResolvedValue({ ...PAGE, status: 'unpublished' });
    await act(async () => {
      button('Take down').click();
    });
    expect(api.updateSite).toHaveBeenCalledWith(3, { status: 'unpublished' });
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    );
    await act(async () => {
      button('Delete').click();
    });
    expect(api.deleteSite).not.toHaveBeenCalled();
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    );
    api.deleteSite.mockResolvedValue(undefined);
    await act(async () => {
      button('Delete').click();
    });
    expect(api.deleteSite).toHaveBeenCalledWith(3);
  });

  it('holds short links back while the cap is 0 (a hosted account, email unconfirmed)', async () => {
    await show();
    expect(host.textContent).toContain('Add one in Settings');
    expect(host.querySelector('input[type=url]')!.matches(':disabled')).toBe(true);
    await act(async () => {
      root.unmount();
    });
    root = createRoot(host);
    // A server that sends no mail has no email form to point at.
    await show({ mail: false });
    expect(host.textContent).toContain('this server sends no mail');
    expect(host.textContent).not.toContain('Add one in Settings');
    await act(async () => {
      root.unmount();
    });
    root = createRoot(host);
    // A one-list self-host gets short links with no email at all.
    await show({ hosted: false }, [PAGE], { pages: 1000, links: 1000 });
    expect(host.textContent).not.toContain('Short links need a confirmed email');
    api.createLink.mockResolvedValue({ ...PAGE, id: 4, kind: 'link', target: 'https://example.com' });
    type(host.querySelector<HTMLInputElement>('input[type=url]')!, 'https://example.com');
    await act(async () => {
      button('Make a short link').click();
    });
    expect(api.createLink).toHaveBeenCalledWith({ url: 'https://example.com', name: undefined });
  });
});
