// Which app of the suite this page is (backend/apps.py). One bundle serves every
// app; the server names the app in a `gtd-app` meta on any host but the anchor's
// (backend/pages.py _shell), and Root.tsx picks the app's pages from it.

/** Each app's product name, by its key in backend/apps.py. */
export const APP_TITLES: Record<string, string> = {
  todo: 'Todo GTD',
  projects: 'Projects GTD',
  sites: 'Simple Sites',
  notes: 'Notes GTD',
  brain: 'Common Brain',
};

/** Each app's name in the suite's app bar, in the bar's order. */
export const APP_SHORT: Record<string, string> = {
  brain: 'Brain',
  todo: 'Todo',
  notes: 'Notes',
  sites: 'Sites',
  projects: 'Projects',
};

function detectApp(): string {
  // Outside a browser (vitest's Node environment) there is no page to ask.
  if (typeof document === 'undefined') return 'todo';
  const key = document.querySelector('meta[name="gtd-app"]')?.getAttribute('content') ?? '';
  return key in APP_TITLES ? key : 'todo';
}

export const APP = detectApp();
export const APP_TITLE = APP_TITLES[APP];

/** Path of this app on the main host; empty on a configured app host. */
export const BASE =
  typeof document === 'undefined'
    ? ''
    : (document.querySelector('meta[name="gtd-base"]')?.getAttribute('content') ?? '');
