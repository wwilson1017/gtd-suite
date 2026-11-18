import { BASE, APP, APP_TITLES } from '../../../core/app';

// Each app's mark is its own tile in its own palette, one suite by the shared check
// breaking out of a shape: Todo a red box, Notes a yellow legal pad, Projects a green
// stack of boxes, Sites a blue browser window. The tile is the app's favicon
// (public/icon*.svg), so the page shows that file and the two cannot drift; the
// home-screen PNGs are drawn from the same art.

/** An app's mark (this page's app by default). */
export function Logo({ className, app = APP }: { className?: string; app?: string }) {
  const key = app in APP_TITLES ? app : 'todo';
  return <img src={key === 'todo' ? BASE + '/icon.svg' : `${BASE}/icon-${key}.svg`} alt="" className={className} />;
}

/** Each app's colour, readable on the page in either theme (index.css): its name's
 *  last word, and its tab's underline in the app bar. */
export const APP_TEXT: Record<string, string> = {
  todo: 'text-brand-mark',
  notes: 'text-notes-ink',
  projects: 'text-projects-ink',
  sites: 'text-sites-ink',
  brain: 'text-brain-ink',
};
export const APP_BORDER: Record<string, string> = {
  todo: 'border-brand-mark',
  notes: 'border-notes-ink',
  projects: 'border-projects-ink',
  sites: 'border-sites-ink',
  brain: 'border-brain-ink',
};

/** An app's name with its last word in the app's colour: Notes GTD, Simple Sites. */
export function AppName({ app = APP }: { app?: string }) {
  const key = app in APP_TITLES ? app : 'todo';
  const title = APP_TITLES[key];
  const cut = title.lastIndexOf(' ');
  return (
    <>
      {title.slice(0, cut)} <span className={APP_TEXT[key]}>{title.slice(cut + 1)}</span>
    </>
  );
}
