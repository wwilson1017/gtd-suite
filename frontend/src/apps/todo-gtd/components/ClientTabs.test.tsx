// @vitest-environment jsdom
//
// Pick your AI: a tab per tool most people use, its steps carrying the real agent link,
// and every other tool under More.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CLIENTS } from '../clients';
import { ClientTabs } from './ClientTabs';

const LINK = 'https://todo.example/link/TOKEN';
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const tabs = () => [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
const selected = () =>
  tabs()
    .filter((t) => t.getAttribute('aria-selected') === 'true')
    .map((t) => t.textContent);
const panel = () => host.querySelector('[role="tabpanel"]')!;
async function pick(label: string) {
  await act(async () => {
    tabs()
      .find((t) => t.textContent === label)!
      .click();
  });
}

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<ClientTabs url={LINK} />);
  });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  host.remove();
});

describe('the pick-your-AI tabs', () => {
  it('opens on the first tool, with its steps and the link to paste', () => {
    expect(tabs().map((t) => t.textContent)).toEqual([
      'ChatGPT',
      'Claude',
      'Grok',
      'Gemini',
      'Claude Code',
      'Codex',
      'More',
    ]);
    expect(selected()).toEqual(['ChatGPT']);
    expect(panel().querySelectorAll('ol li')).toHaveLength(3);
    expect(panel().querySelector('code')!.textContent).toBe(LINK);
    expect(panel().querySelector('button[aria-label="Copy your agent link"]')).not.toBeNull();
  });

  it('shows a coding tool its command with the link filled in', async () => {
    await pick('Claude Code');
    expect(selected()).toEqual(['Claude Code']);
    expect(panel().querySelector('code')!.textContent).toBe(`claude mcp add --transport http gtd ${LINK}`);
    expect(panel().querySelector('button[aria-label="Copy the Claude Code setup"]')).not.toBeNull();
    expect(panel().querySelector('ol')).toBeNull();
  });

  it('keeps every other tool under More', async () => {
    await pick('More');
    expect(selected()).toEqual(['More']);
    const listed = [...panel().querySelectorAll('summary')].map((s) => s.textContent);
    expect(listed).toEqual(CLIENTS.map((c) => c.name));
    expect(listed).toContain('Cursor');
  });

  it('leads Grok with the one message to paste into a chat, then its connector', async () => {
    await pick('Grok');
    expect(panel().textContent).toContain('Paste this message into any Grok chat. That is all.');
    expect(panel().querySelector('pre')!.textContent).toBe(
      `Open ${LINK} and show me my next actions. It is my own todo list, and that page explains how to read and update it.`,
    );
    expect(panel().querySelector('button[aria-label="Copy the message for Grok"]')).not.toBeNull();
    expect(panel().textContent).toContain('Or add it as a connector');
    expect(panel().querySelectorAll('ol li')).toHaveLength(3);
  });

  it('has a tool behind every tab', () => {
    // A tab whose name matches nothing in CLIENTS would open an empty panel.
    for (const tab of tabs().slice(0, -1)) {
      act(() => tab.click());
      expect(panel().textContent, tab.textContent!).toContain(LINK);
    }
  });
});
