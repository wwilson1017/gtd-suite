// @vitest-environment jsdom
//
// The shell marks the current list — once, with aria-current="page" — in each of
// its three menus: top row, phone bottom bar, sidebar. The mode comes from two
// media queries plus the stored layout preference, so matchMedia is stubbed. Its header
// carries Your AI and the Settings gear, and under it sit the "Connect your AI" card
// (until an AI tool has called, or the person dismisses it) and the "keep this list"
// banner (on every page but Settings).
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  getFilters: vi.fn().mockResolvedValue({ contexts: [], tags: [], status_counts: { inbox: 3 } }),
  listProjects: vi.fn().mockResolvedValue([]),
  getSession: vi.fn(),
  getAiTools: vi.fn(),
}));

import { saveMenuLayout } from '../../core/theme/menuLayout';
import { getAiTools, getFilters, getSession } from './api';
import { PHONE_QUERY, SIDEBAR_QUERY } from './menu';
import { bootstrap, resetSession } from './session';
import { TodoShell, type TodoTab } from './TodoShell';

let container: HTMLDivElement;
let root: Root;

function setScreen(matching: string[]) {
  window.matchMedia = ((q: string) => ({
    matches: matching.includes(q),
    media: q,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

async function render(active: TodoTab) {
  await act(async () => {
    root.render(
      <MemoryRouter>
        <TodoShell active={active} hideQuickAdd>
          <p>page body</p>
        </TodoShell>
      </MemoryRouter>,
    );
  });
}

const navLabels = () => [...container.querySelectorAll('nav')].map((n) => n.getAttribute('aria-label'));
const current = () => [...container.querySelectorAll('[aria-current="page"]')].map((e) => e.textContent);
const more = () => [...container.querySelectorAll('button')].find((b) => b.textContent?.startsWith('More'));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  saveMenuLayout('top');
  resetSession();
});

describe('TodoShell menus', () => {
  it('top menu: two navs, the current list marked in whichever tier holds it', async () => {
    setScreen([]);
    await render('next');
    expect(navLabels()).toEqual(['Main lists', 'Other lists']);
    expect(current()).toEqual(['To Do']);
    expect(container.textContent).toContain('page body');

    await render('review');
    expect(current()).toEqual(['Review']);
    // jsdom has no layout, so nothing overflows and there is no More.
    expect(more()).toBeUndefined();
  });

  it('top menu: what does not fit moves into More, never the current list', async () => {
    // jsdom has no layout, so give it one: six 50px items in the ruler (the five
    // lists and More) plus 10px of divider, in a slot 170px wide.
    const offset = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')!;
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
      configurable: true,
      get(this: HTMLElement) {
        return this.tagName === 'SPAN' ? 50 : 310;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 170 });
    try {
      setScreen([]);
      await render('review');
      const other = container.querySelector('nav[aria-label="Other lists"]')!;
      expect([...other.querySelectorAll(':scope > a')].map((a) => a.textContent)).toEqual(['Areas', 'Review']);
      expect(current()).toEqual(['Review']);
      const button = more()!;
      expect(button.hasAttribute('aria-current')).toBe(false);
      await act(async () => {
        button.click();
      });
      const panel = document.getElementById(button.getAttribute('aria-controls')!)!;
      expect([...panel.querySelectorAll('a')].map((a) => a.textContent)).toEqual(['Waiting', 'Someday', 'Done']);

      // A press inside keeps it open; a press or keyboard focus outside closes it.
      await act(async () => {
        panel.dispatchEvent(new Event('pointerdown', { bubbles: true }));
      });
      expect(button.getAttribute('aria-expanded')).toBe('true');
      await act(async () => {
        document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
      });
      expect(button.getAttribute('aria-expanded')).toBe('false');
      await act(async () => {
        button.click();
      });
      await act(async () => {
        container.querySelector('input')!.focus();
      });
      expect(button.getAttribute('aria-expanded')).toBe('false');
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'offsetWidth', offset);
      delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
    }
  });

  it('top menu: shows the inbox count and no tagline', async () => {
    setScreen([]);
    await render('inbox');
    expect(current()).toEqual(['Inbox3']);
    expect(container.textContent).not.toContain('Mind like water');
  });

  it('phone: one bottom bar; a secondary list is reached and marked through More', async () => {
    setScreen([PHONE_QUERY]);
    await render('projects');
    expect(navLabels()).toEqual(['Main lists']);
    expect(current()).toEqual(['Projects']);
    expect(more()!.hasAttribute('aria-current')).toBe(false);

    await render('waiting');
    expect(current()).toEqual([]); // the sheet is closed
    const button = more()!;
    expect(button.getAttribute('aria-current')).toBe('true'); // so More carries the marking
    expect(button.getAttribute('aria-expanded')).toBe('false');
    await act(async () => {
      button.click();
    });
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(current()).toEqual(['Waiting']);
    const sheet = document.getElementById(button.getAttribute('aria-controls')!)!;
    expect([...sheet.querySelectorAll('a')].map((a) => a.textContent)).toEqual([
      'Areas',
      'Waiting',
      'Someday',
      'Review',
      'Done',
    ]);

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(button.getAttribute('aria-expanded')).toBe('false');
  });

  it('sidebar: all ten lists in one nav when chosen on a wide screen', async () => {
    setScreen([SIDEBAR_QUERY]);
    await act(async () => {
      saveMenuLayout('sidebar');
    });
    await render('someday');
    expect(navLabels()).toEqual(['Lists']);
    expect(container.querySelectorAll('nav a')).toHaveLength(10);
    expect(current()).toEqual(['Someday']);
  });

  it('sidebar preference falls back to the top menu below the wide breakpoint', async () => {
    setScreen([]);
    await act(async () => {
      saveMenuLayout('sidebar');
    });
    await render('done');
    expect(navLabels()).toEqual(['Main lists', 'Other lists']);
    expect(current()).toEqual(['Done']);
  });

  it('Settings marks no list, only the gear; Your AI only its own button beside it', async () => {
    setScreen([]);
    await render('connect');
    expect(container.querySelectorAll('nav [aria-current="page"]')).toHaveLength(0);
    expect(current()).toEqual(['⚙']);
    const gear = container.querySelector('[aria-current="page"]')!;
    expect(gear.getAttribute('aria-label')).toBe('Settings');
    expect(gear.getAttribute('href')).toBe('/connect'); // the address is older than the name
    expect(gear.previousElementSibling!.textContent).toBe('Your AI');
    expect(gear.previousElementSibling!.getAttribute('href')).toBe('/ai');

    await render('ai');
    expect(container.querySelectorAll('nav [aria-current="page"]')).toHaveLength(0);
    expect(current()).toEqual(['Your AI']);
  });
});

describe('the list name in the shell', () => {
  const filters = (name: string) => ({ contexts: [], tags: [], status_counts: { inbox: 3 }, name }) as never;

  it('shows the generic title until the list has a name, then the name, in header and tab', async () => {
    setScreen([]);
    await render('today');
    expect(container.querySelector('h1')!.textContent).toBe('Todo GTD');
    expect(document.title).toBe('Todos');

    vi.mocked(getFilters).mockResolvedValue(filters('Home & garden'));
    await act(async () => {
      root.unmount();
    });
    root = createRoot(container);
    await render('today');
    expect(container.querySelector('h1')!.textContent).toBe('Home & garden');
    expect(document.title).toBe('Home & garden');

    // The sidebar's heading follows it too.
    setScreen([SIDEBAR_QUERY]);
    await act(async () => {
      saveMenuLayout('sidebar');
    });
    await render('today');
    expect([...container.querySelectorAll('h1')].map((h) => h.textContent)).toEqual(['Home & garden']);
    vi.mocked(getFilters).mockResolvedValue(filters(''));
  });
});

describe('the keep-this-list banner in the shell', () => {
  const KEEP = 'This list lives in this browser.';

  it('sits under the header on every page but Settings, where the email field is right there', async () => {
    vi.mocked(getSession).mockResolvedValue({
      list_id: 7,
      state: 'active',
      email: null,
      verified: false,
      hosted: true,
      mail: true,
      caps: { todos: 200, projects: 20, areas: 10 },
      apps: ['todo'],
    });
    resetSession();
    await act(async () => {
      await bootstrap();
    });
    setScreen([]);
    await render('next');
    expect(container.textContent).toContain(KEEP);

    await render('connect');
    expect(container.textContent).not.toContain(KEEP);

    await render('inbox');
    expect(container.textContent).toContain(KEEP);
  });
});

describe('the Connect your AI card in the shell', () => {
  const CARD = 'Give Claude, ChatGPT or another AI one link';
  const CLAUDE = { name: 'Claude', last_used: '2026-11-02', days_ago: 0 };

  async function signedIn(session: object = {}) {
    vi.mocked(getSession).mockResolvedValue({
      list_id: 7,
      state: 'active',
      email: null,
      verified: false,
      hosted: true,
      mail: true,
      caps: { todos: 200, projects: 20, areas: 10 },
      apps: ['todo', 'notes', 'projects'],
      ai_tools: [],
      ...session,
    });
    resetSession();
    await act(async () => {
      await bootstrap();
    });
    setScreen([]);
  }
  const focus = () =>
    act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

  beforeEach(() => {
    localStorage.clear();
    vi.mocked(getAiTools).mockReset();
  });

  it('is pinned above the keep banner until an AI tool has called, and opens Your AI', async () => {
    await signedIn();
    await render('today');
    const text = container.textContent!;
    expect(text).toContain(CARD);
    expect(text.indexOf(CARD)).toBeLessThan(text.indexOf('This list lives in this browser.'));
    const open = [...container.querySelectorAll('a')].filter((a) => a.textContent === 'Connect your AI');
    expect(open.map((a) => a.getAttribute('href'))).toEqual(['/ai']);
    // Not on the page it opens, nor on Settings.
    await render('ai');
    expect(container.textContent).not.toContain(CARD);
    await render('connect');
    expect(container.textContent).not.toContain(CARD);

    // An account an AI has already called never sees it.
    await signedIn({ ai_tools: [CLAUDE] });
    await render('today');
    expect(container.textContent).not.toContain(CARD);
  });

  it('goes by itself, without a reload, once an AI has made its first call', async () => {
    await signedIn();
    const loads = vi.mocked(getSession).mock.calls.length;
    await render('inbox');
    expect(container.textContent).toContain(CARD);
    expect(getAiTools).not.toHaveBeenCalled(); // the session answer already said: none

    // The person comes back to the window before anything has called: still there.
    vi.mocked(getAiTools).mockResolvedValue([]);
    await focus();
    expect(getAiTools).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain(CARD);

    // Their AI makes its first call, elsewhere; then the window is in focus again.
    vi.mocked(getAiTools).mockResolvedValue([CLAUDE]);
    await focus();
    expect(container.textContent).not.toContain(CARD);
    expect(container.textContent).toContain('page body');
    expect(getSession).toHaveBeenCalledTimes(loads); // the same page load throughout

    // Gone, it stops asking.
    await focus();
    expect(getAiTools).toHaveBeenCalledTimes(2);
  });

  it('stays through a failed ask, and asks again the next time', async () => {
    await signedIn();
    await render('today');
    vi.mocked(getAiTools).mockRejectedValueOnce(new Error('offline')).mockResolvedValue([CLAUDE]);
    await focus();
    expect(container.textContent).toContain(CARD);
    await focus();
    expect(container.textContent).not.toContain(CARD);
  });

  it('can be dismissed, for this list on this device', async () => {
    await signedIn();
    await render('today');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('button[aria-label="Dismiss Connect your AI"]')!.click();
    });
    expect(container.textContent).not.toContain(CARD);
    // The keep banner has its own dismissal.
    expect(container.textContent).toContain('This list lives in this browser.');
    await focus();
    expect(getAiTools).not.toHaveBeenCalled();

    // A new page of the same list: still dismissed. Another list: its own card.
    await act(async () => {
      root.unmount();
    });
    root = createRoot(container);
    await render('today');
    expect(container.textContent).not.toContain(CARD);
    await signedIn({ list_id: 8 });
    await act(async () => {
      root.unmount();
    });
    root = createRoot(container);
    await render('today');
    expect(container.textContent).toContain(CARD);
  });
});
