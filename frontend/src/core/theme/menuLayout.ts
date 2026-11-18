/**
 * Menu layout preference: Top menu (the default) or Sidebar. Per device, in
 * localStorage, the same way as the theme (theme.ts): the default is stored as the
 * absence of a value, and blocked storage degrades to "applies for this page only".
 */
import { useSyncExternalStore } from 'react';

export type MenuLayout = 'top' | 'sidebar';

export const MENU_LAYOUT_KEY = 'todo-gtd-menu-layout';

export function readMenuLayout(): MenuLayout {
  try {
    return localStorage.getItem(MENU_LAYOUT_KEY) === 'sidebar' ? 'sidebar' : 'top';
  } catch {
    return 'top'; // storage blocked (private mode, embedded webview)
  }
}

// The choice made on this page, so it applies even when storage refused it — and
// what lets the shell re-render when the Connect page's select changes it.
let chosen: MenuLayout | null = null;
const listeners = new Set<() => void>();

/** Remember the choice (best effort) and apply it now. */
export function saveMenuLayout(layout: MenuLayout): void {
  try {
    if (layout === 'top') localStorage.removeItem(MENU_LAYOUT_KEY);
    else localStorage.setItem(MENU_LAYOUT_KEY, layout);
  } catch {
    // Not remembered — still applied for this page.
  }
  chosen = layout;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useMenuLayout(): [MenuLayout, (l: MenuLayout) => void] {
  return [useSyncExternalStore(subscribe, () => chosen ?? readMenuLayout()), saveMenuLayout];
}

/** Live result of a media query; false where there is no matchMedia. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia?.(query);
      if (!mq) return () => {};
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    },
    () => window.matchMedia?.(query).matches ?? false,
  );
}
