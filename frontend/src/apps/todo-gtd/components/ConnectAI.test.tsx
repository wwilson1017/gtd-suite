// @vitest-environment jsdom
//
// Settings › Connect your AI: the status (which AI tools have called, and the day each
// last did, or waiting), the pick-your-AI tabs, and the agent link with its copy button;
// nothing else. The status follows a first call without a reload, when the window comes
// back into focus.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AiTool, Session } from '../types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getAiTools: vi.fn(),
  getAgentLink: vi.fn(),
  regenerateAgentLink: vi.fn(),
}));
// A full mock: the real api.ts imports session.ts, which would bind to the real getSession.
vi.mock('../api', () => api);

import { bootstrap, resetSession } from '../session';
import { ConnectAI } from './ConnectAI';

const LINK = 'https://todo.example/link/TOKEN';
const SESSION: Session = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['todo', 'notes', 'projects'],
  ai_tools: [],
};
const tool = (name: string, days_ago: number | null = null, last_used: string | null = null): AiTool => ({
  name,
  days_ago,
  last_used: last_used ?? (days_ago === null ? null : '2026-11-02'),
});

describe('Connect your AI', () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  async function show(session: Partial<Session> = {}) {
    resetSession();
    api.getSession.mockResolvedValue({ ...SESSION, ...session });
    await act(async () => {
      await bootstrap();
    });
    await act(async () => {
      root.render(<ConnectAI />);
    });
  }
  const status = () => host.querySelector('[role="status"]')!.textContent;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    api.getAgentLink.mockResolvedValue({ url: LINK, token: 'TOKEN' });
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    host.remove();
  });

  describe('its status line', () => {
    /** The page's status for these tools, a string per line. */
    async function lines(...tools: AiTool[]) {
      await show({ ai_tools: tools });
      return [...host.querySelectorAll('[role="status"] li')].map((li) => li.textContent);
    }

    it('names the tool and the day it last called: today, yesterday, then the date', async () => {
      expect(await lines(tool('Claude', 0))).toEqual(['Claude connected · last used today']);
      expect(await lines(tool('Claude', 1))).toEqual(['Claude connected · last used yesterday']);
      expect(await lines(tool('Claude', 13, '2026-10-20'))).toEqual(['Claude connected · last used Oct 20, 2026']);
    });

    it('never shows a time', async () => {
      const text = (await lines(tool('Claude', 0), tool('Codex', 1), tool('Grok', 400, '2025-09-28'))).join(' ');
      expect(text).toContain('Sep 28, 2025');
      expect(text).not.toMatch(/\d:\d|\b[ap]m\b/i);
    });

    it('says only "connected" for a tool known from what it wrote before the record began', async () => {
      expect(await lines(tool('Grok'))).toEqual(['Grok connected']);
    });

    it('calls a tool that gave no name "An AI tool", and leaves it out once a named one exists', async () => {
      expect(await lines(tool('', 0))).toEqual(['An AI tool connected · last used today']);
      expect(await lines(tool('', 0), tool('Claude', 3, '2026-10-30'))).toEqual([
        'Claude connected · last used Oct 30, 2026',
      ]);
    });

    it('gives the three latest callers a line each and the rest one line together', async () => {
      const many = ['Grok', 'ChatGPT', 'Cursor', 'vm-jobs'].map((name) => tool(name));
      expect(await lines(tool('Claude', 0), tool('Codex', 1), ...many)).toEqual([
        'Claude connected · last used today',
        'Codex connected · last used yesterday',
        'Grok connected',
        'Also connected: ChatGPT, Cursor, and vm-jobs',
      ]);
    });
  });

  it('holds the status, the link with its copy button and regenerate, and the steps for each AI', async () => {
    await show();
    expect(status()).toContain('Waiting for your AI. This turns green the first time it uses your link.');
    expect(host.textContent).toContain('Pick your AI');
    expect(host.querySelector<HTMLInputElement>('input[readonly]')!.value).toBe(LINK);
    expect(host.querySelector('button[aria-label="Copy the agent link"]')).not.toBeNull();
    expect([...host.querySelectorAll('button')].some((b) => b.textContent === 'Make a new link…')).toBe(true);
    // The walk-through travels with the link.
    expect(host.textContent).toContain('Watch how');
    const tabs = [...host.querySelectorAll('[role="tab"]')].map((t) => t.textContent);
    expect(tabs).toEqual(['ChatGPT', 'Claude', 'Grok', 'Gemini', 'Claude Code', 'Codex', 'More']);
    expect(host.querySelector('[role="tabpanel"]')!.textContent).toContain(LINK);
    // Nothing of the other sections is here.
    for (const other of ['Your email', 'Capture link', 'Sign out', 'Time zone', 'Your apps']) {
      expect(host.textContent).not.toContain(other);
    }
  });

  it('says which AI is connected, as text', async () => {
    const name = '<img src=x onerror=alert(1)>';
    await show({ ai_tools: [tool(name, 0), tool('Codex', 1)] });
    expect(status()).toBe(`${name} connected · last used todayCodex connected · last used yesterday`);
    expect(host.querySelector('[role="status"] img')).toBeNull();
  });

  it('follows the first call without a reload, when the window comes back into focus', async () => {
    await show();
    expect(api.getAiTools).not.toHaveBeenCalled();
    api.getAiTools.mockResolvedValue([tool('Claude', 0)]);
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });
    expect(status()).toBe('Claude connected · last used today');
    expect(host.textContent).toContain('Add another AI');
    expect(api.getSession).toHaveBeenCalledTimes(1);
  });
});
