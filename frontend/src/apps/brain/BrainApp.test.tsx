// @vitest-environment jsdom
//
// The boot path on Common Brain's address: Root mounts the brain on /app once the
// session names the list, every brain request carries X-List, and each memory shows
// which AI wrote it, its lock, and the email nudge at the one-AI limit. A page shows its
// frontmatter as properties and its [[links]] as links; the nav's box searches.
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
  apps: ['todo', 'brain'],
};
const AT = '2026-10-24T12:00:00Z';
const OVERVIEW = {
  memories: [
    {
      id: 1,
      text: 'Short answers, no bullet points',
      locked: true,
      status: 'active',
      version: 2,
      created_by: 'ChatGPT',
      updated_by: 'you',
      created_at: AT,
      updated_at: AT,
    },
    {
      id: 2,
      text: 'Training for a half marathon in March',
      locked: false,
      status: 'active',
      version: 1,
      created_by: 'ChatGPT',
      updated_by: 'ChatGPT',
      created_at: AT,
      updated_at: AT,
    },
  ],
  pages: [
    {
      id: 3,
      path: 'people/sam',
      title: 'Sam',
      format: 'markdown',
      status: 'active',
      version: 1,
      created_by: 'Claude',
      updated_by: 'Claude',
      created_at: AT,
      updated_at: AT,
      size: 20,
    },
  ],
  folders: [{ folder: 'people', pages: 1 }],
  ais: [{ name: 'ChatGPT', first_seen_at: AT, last_seen_at: AT, onboarded_at: AT }],
  caps: { ais: 1, memories: 50, pages: 10 },
  nudge: true,
  custom_instruction: 'I use Common Brain…',
  misses: [{ query: 'wifi password', asked: 3, last: AT }],
};

let overviewCalls = 0;
// From the second overview on, an AI has changed memory 2: new text, version 2.
function overview() {
  if (++overviewCalls < 2) return OVERVIEW;
  const [a, b] = OVERVIEW.memories;
  return { ...OVERVIEW, memories: [a, { ...b, text: 'Training for a full marathon', version: 2 }] };
}

const PAGE = {
  ...OVERVIEW.pages[0],
  body: '---\nstatus: active\ntags: [family, work]\n---\nSam works with [[Maya|Maya L]] on [[the plan]].',
};

function answer(path: string): { status: number; body: unknown } {
  if (path === '/api/app/session') return { status: 200, body: SESSION };
  if (path === '/api/app/brain') return { status: 200, body: overview() };
  if (path === '/api/app/brain/pages/3') return { status: 200, body: PAGE };
  if (path === '/api/app/brain/resolve')
    return { status: 200, body: { links: { Maya: { kind: 'page', id: 9, path: 'people/maya' } } } };
  if (path === '/api/app/brain/search')
    return {
      status: 200,
      body: { memories: [OVERVIEW.memories[1]], pages: [{ ...OVERVIEW.pages[0], snippet: 'Sam runs too' }] },
    };
  if (path === '/api/config') return { status: 200, body: { app: 'brain', apps: {} } };
  return { status: 404, body: { detail: 'Not found' } };
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot> | null = null;
let fetchMock: ReturnType<typeof vi.fn>;
let meta: HTMLMetaElement;

beforeEach(() => {
  overviewCalls = 0;
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  meta = document.createElement('meta');
  meta.name = 'gtd-app';
  meta.content = 'brain';
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

describe('Root on Common Brain', () => {
  it('mounts the brain on /app, with who wrote each memory and the list on every request', async () => {
    const { default: Root } = await import('../../Root');
    root = createRoot(host);
    await act(async () => {
      root!.render(<Root />);
    });
    await settle('Training for a half marathon');

    expect(host.textContent).toContain('Common Brain');
    expect(host.textContent).toContain('2 of 50');
    expect(host.textContent).toContain('Add your email to keep growing');
    expect(host.textContent).toContain('Sam');
    // What AIs searched for and did not find.
    expect(host.querySelector('[aria-labelledby="cb-misses"]')!.textContent).toContain('wifi password');
    expect(host.textContent).toContain('asked 3 times');
    // The connected AIs show when each last opened the brain, never a set-up state.
    const strip = host.querySelector('[aria-label="Connected AIs"]')!.textContent;
    expect(strip).toContain('ChatGPT');
    expect(strip).toContain('opened');
    expect(strip).not.toContain('set up');
    expect(host.querySelector('button[aria-label^="Unlock"]')).not.toBeNull();
    expect(host.querySelectorAll('button[aria-label^="Lock"]')).toHaveLength(1);
    const brainCalls = fetchMock.mock.calls
      .filter(([url]) => String(url).startsWith('/api/app/brain'))
      .map(
        ([, init]) => ((init as RequestInit | undefined)?.headers as Record<string, string> | undefined)?.['X-List'],
      );
    expect(brainCalls.length).toBeGreaterThan(0);
    expect(brainCalls.every((x) => x === '7')).toBe(true);
  }, 30_000);

  it('edits the latest text but saves against the version the editor opened on', async () => {
    const { default: Root } = await import('../../Root');
    root = createRoot(host);
    await act(async () => {
      root!.render(<Root />);
    });
    await settle('Training for a half marathon');
    const row = () => [...host.querySelectorAll('li')].find((li) => li.textContent?.includes('Training for a'))!;
    const open = () => [...row().querySelectorAll('button')].find((b) => b.textContent?.startsWith('Training for a'))!;
    // The row mounted with the old text; the 4 s refresh (real timers) brings the AI's change.
    await settle('full marathon');
    await act(async () => {
      open().click();
    });
    const input = host.querySelector('input[aria-label="The memory"]') as HTMLInputElement;
    expect(input.value).toBe('Training for a full marathon');
    fetchMock.mockImplementationOnce(async () => new Response('{}', { status: 200 }));
    await act(async () => {
      input.form!.requestSubmit();
    });
    const put = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')!;
    expect(JSON.parse((put[1] as RequestInit).body as string)).toEqual({
      text: 'Training for a full marathon',
      version: 2,
    });
  }, 30_000);

  it('saves a review date when the box is left, not while it is typed', async () => {
    const { default: Root } = await import('../../Root');
    root = createRoot(host);
    await act(async () => {
      root!.render(<Root />);
    });
    await settle('Training for a half marathon');
    const box = host.querySelector('input[aria-label="Review by"]') as HTMLInputElement;
    const puts = () => fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT');
    await act(async () => {
      box.value = '0002-04-15'; // what the browser reports mid-typing
      box.dispatchEvent(new Event('input', { bubbles: true }));
      box.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(puts()).toHaveLength(0);
    fetchMock.mockImplementationOnce(async () => new Response('{}', { status: 200 }));
    await act(async () => {
      box.value = '2028-04-15';
      box.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    });
    expect(puts()).toHaveLength(1);
    expect(JSON.parse((puts()[0][1] as RequestInit).body as string)).toMatchObject({ review_on: '2028-04-15' });
  }, 30_000);

  it("shows a page's properties and resolves its [[links]] in one batch", async () => {
    window.history.replaceState({}, '', '/app/p/3');
    const { default: Root } = await import('../../Root');
    root = createRoot(host);
    await act(async () => {
      root!.render(<Root />);
    });
    await settle('Sam works with');
    const props = host.querySelector('dl[aria-label="Properties"]')!;
    expect([...props.querySelectorAll('dt')].map((d) => d.textContent)).toEqual(['status', 'tags']);
    expect(props.textContent).toContain('family, work');
    expect(host.textContent).not.toContain('---');
    const resolve = fetchMock.mock.calls.filter(([url]) => String(url) === '/api/app/brain/resolve');
    expect(resolve).toHaveLength(1);
    expect(JSON.parse((resolve[0][1] as RequestInit).body as string)).toEqual({ targets: ['Maya', 'the plan'] });
    await settle('Maya L');
    const deadline = Date.now() + 5000;
    while (!host.querySelector('a[href="/app/p/9"]') && Date.now() < deadline) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 10));
      });
    }
    expect(host.querySelector('a[href="/app/p/9"]')?.textContent).toBe('Maya L');
    expect(host.querySelector('.cb-wiki-missing')?.textContent).toBe('the plan');
  }, 30_000);

  it('searches from the nav, shows the results in place of the page, and opens one', async () => {
    window.history.replaceState({}, '', '/app/p/3'); // the result is this same page
    const { default: Root } = await import('../../Root');
    root = createRoot(host);
    await act(async () => {
      root!.render(<Root />);
    });
    await settle('Sam works with');
    const box = host.querySelector('input[aria-label="Search your brain"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(box, 'runs');
      box.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await settle('Sam runs too');
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/app/brain/search?q=runs')).toBe(true);
    const result = host.querySelector('section[aria-label="Search results"] a[href="/app/p/3"]') as HTMLAnchorElement;
    await act(async () => {
      result.click();
    });
    expect(host.querySelector('section[aria-label="Search results"]')).toBeNull();
    expect(box.value).toBe('');
    expect(host.textContent).toContain('Sam works with');
  }, 30_000);
});
