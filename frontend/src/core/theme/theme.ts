/**
 * Light / Dark / System theme preference.
 *
 * The preference lives in localStorage; "system" (the default) is stored as the
 * absence of a value, so a fresh browser simply follows the OS. The resolved theme
 * is the `dark` class on <html>, which index.css keys every token off.
 *
 * index.html carries an inline copy of the read + resolve below so the class is set
 * before first paint — keep the storage key and the rule in step with it.
 */
import { useEffect, useState } from 'react';

export type ThemePref = 'light' | 'dark' | 'system';

export const THEME_KEY = 'todo-gtd-theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

export function readThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system'; // storage blocked (private mode, embedded webview)
  }
}

export function resolveDark(pref: ThemePref, osDark: boolean): boolean {
  return pref === 'dark' || (pref === 'system' && osDark);
}

function osDark(): boolean {
  return window.matchMedia?.(DARK_QUERY).matches ?? false;
}

export function applyTheme(pref: ThemePref): void {
  document.documentElement.classList.toggle('dark', resolveDark(pref, osDark()));
}

/** Remember the choice (best effort) and apply it now. */
export function saveThemePref(pref: ThemePref): void {
  try {
    if (pref === 'system') localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, pref);
  } catch {
    // Not remembered — still applied for this page.
  }
  applyTheme(pref);
}

/** The preference plus a setter; follows the OS live while the choice is "system". */
export function useThemePref(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState(readThemePref);

  useEffect(() => {
    if (pref !== 'system') return;
    const mq = window.matchMedia?.(DARK_QUERY);
    if (!mq) return;
    const onChange = () => applyTheme('system');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [pref]);

  return [
    pref,
    (p) => {
      saveThemePref(p);
      setPref(p);
    },
  ];
}
