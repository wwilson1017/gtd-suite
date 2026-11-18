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
  todo: 'Todo',
  notes: 'Notes',
  projects: 'Projects',
  sites: 'Sites',
  brain: 'Brain',
};

/** The apps that live together at the main address (backend/apps.py FAMILY): always
 *  tabs in the app bar. Another app is a tab once the account has it on. */
export const FAMILY = ['todo', 'notes', 'projects'];

/** One line about an app, where the app bar's "More" menu offers it. */
export const APP_LINES: Record<string, string> = {
  sites: 'A place to park the pages your AI makes.',
  brain: 'What your AI knows, shared by every AI you use.',
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
