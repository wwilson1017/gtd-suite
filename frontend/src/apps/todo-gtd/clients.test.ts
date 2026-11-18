import { describe, expect, it, vi } from 'vitest';
import { CLIENTS, pastePrompt } from './clients';

const URL_ = 'https://todogtd.example/link/AGENT';

describe('per-client setup', () => {
  const client = (name: string) => CLIENTS.find((c) => c.name === name)!;

  it('every client has a way in, and none of them sends a header', () => {
    for (const c of CLIENTS) {
      expect(c.deeplink || c.command || c.steps, c.name).toBeTruthy();
      expect(c.command?.(URL_) ?? '', c.name).not.toMatch(/authorization|bearer|header/i);
    }
  });

  it('the Cursor deeplink carries the link as base64 JSON config', () => {
    const link = new URL(client('Cursor').deeplink!(URL_));
    expect(link.protocol).toBe('cursor:');
    expect(JSON.parse(atob(link.searchParams.get('config')!))).toEqual({ url: URL_ });
  });

  it('the VS Code deeplink carries the link as URL-encoded JSON', () => {
    const link = client('VS Code').deeplink!(URL_);
    expect(link.startsWith('vscode:mcp/install?')).toBe(true);
    expect(JSON.parse(decodeURIComponent(link.slice('vscode:mcp/install?'.length)))).toEqual({
      name: 'gtd',
      type: 'http',
      url: URL_,
    });
  });

  it('covers every tool, and every command carries the real link', () => {
    for (const c of CLIENTS) {
      if (c.command) expect(c.command(URL_), c.name).toContain(URL_);
    }
    expect(CLIENTS.map((c) => c.name)).toEqual([
      'Cursor',
      'VS Code',
      'Claude Code',
      'Codex',
      'Gemini CLI',
      'Claude (claude.ai)',
      'ChatGPT',
      'Grok',
      'Gemini',
      'Le Chat',
      'Perplexity',
    ]);
  });

  it('the paste message opens the link as a page and names no protocol', () => {
    const message = pastePrompt(URL_);
    expect(message.startsWith(`Open ${URL_} and show me my next actions.`)).toBe(true);
    expect(message).not.toMatch(/follow the instructions/);
    expect(message.replace(URL_, '')).not.toMatch(/mcp|server|api|endpoint|token|connect/i);
  });

  it('on Simple Sites the paste message asks for the pages, and names no protocol either', async () => {
    vi.resetModules();
    vi.doMock('../../core/app', async (importOriginal) => ({ ...(await importOriginal<object>()), APP: 'sites' }));
    const { pastePrompt: onSites } = await import('./clients');
    vi.doUnmock('../../core/app');
    const message = onSites(URL_);
    expect(message.startsWith(`Open ${URL_} and show me my pages and short links.`)).toBe(true);
    expect(message.replace(URL_, '')).not.toMatch(/mcp|server|api|endpoint|token|connect/i);
  });

  it('the CLI one-liners use the link as the URL', () => {
    expect(client('Claude Code').command!(URL_)).toBe(`claude mcp add --transport http gtd ${URL_}`);
    expect(client('Codex').command!(URL_)).toBe(`codex mcp add gtd --url ${URL_}`);
    expect(client('Gemini CLI').command!(URL_)).toBe(`gemini mcp add --transport http gtd ${URL_}`);
  });
});
