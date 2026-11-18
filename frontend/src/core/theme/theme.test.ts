// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import indexHtml from '../../../index.html?raw';
import { THEME_KEY, applyTheme, readThemePref, resolveDark, saveThemePref } from './theme';

function setOsDark(dark: boolean) {
  window.matchMedia = ((q: string) => ({ matches: dark, media: q })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.classList.remove('dark');
});

describe('theme preference', () => {
  it('resolves light, dark and system', () => {
    expect(resolveDark('light', true)).toBe(false);
    expect(resolveDark('dark', false)).toBe(true);
    expect(resolveDark('system', true)).toBe(true);
    expect(resolveDark('system', false)).toBe(false);
  });

  it('defaults to system, and ignores a junk stored value', () => {
    expect(readThemePref()).toBe('system');
    localStorage.setItem(THEME_KEY, 'purple');
    expect(readThemePref()).toBe('system');
  });

  it('remembers an explicit choice and applies it over the OS setting', () => {
    setOsDark(false);
    saveThemePref('dark');
    expect(readThemePref()).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);

    setOsDark(true);
    saveThemePref('light');
    expect(readThemePref()).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('system clears the stored value and follows the OS', () => {
    saveThemePref('light');
    setOsDark(true);
    saveThemePref('system');
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    setOsDark(false);
    applyTheme('system');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('survives blocked storage: falls back to system, still applies the choice', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    setOsDark(false);
    expect(readThemePref()).toBe('system');
    saveThemePref('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('the pre-paint script in index.html uses the same storage key', () => {
    expect(indexHtml).toContain(`'${THEME_KEY}'`);
    expect(indexHtml).toContain('</head>');
  });
});
