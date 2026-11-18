/**
 * The menu: ONE definition of the ten lists, read by the top menu, the phone
 * bottom bar and the sidebar. Array order is the display order everywhere.
 *
 * `tier` splits the top menu (primary = the lists you work from, secondary =
 * visited less often); `group` is the sidebar heading. `sub` is the path relative
 * to the app's root ('' = Today) — the router basename carries /app.
 */
export type ListKey =
  'today' | 'inbox' | 'next' | 'search' | 'projects' | 'areas' | 'waiting' | 'someday' | 'review' | 'done';

export interface ListItem {
  key: ListKey;
  label: string;
  sub: string;
  tier: 'primary' | 'secondary';
  group: 'Do' | 'Organize' | 'Parked' | 'Reflect';
}

export const LISTS: ListItem[] = [
  { key: 'today', label: 'Today', sub: '', tier: 'primary', group: 'Do' },
  { key: 'inbox', label: 'Inbox', sub: '/inbox', tier: 'primary', group: 'Do' },
  { key: 'next', label: 'To Do', sub: '/next', tier: 'primary', group: 'Do' },
  { key: 'search', label: 'Contexts', sub: '/search', tier: 'primary', group: 'Do' },
  { key: 'projects', label: 'Projects', sub: '/projects', tier: 'primary', group: 'Organize' },
  { key: 'areas', label: 'Areas', sub: '/areas', tier: 'secondary', group: 'Organize' },
  { key: 'waiting', label: 'Waiting', sub: '/waiting', tier: 'secondary', group: 'Parked' },
  { key: 'someday', label: 'Someday', sub: '/someday', tier: 'secondary', group: 'Parked' },
  { key: 'review', label: 'Review', sub: '/review', tier: 'secondary', group: 'Reflect' },
  { key: 'done', label: 'Done', sub: '/done', tier: 'secondary', group: 'Reflect' },
];

export const PRIMARY = LISTS.filter((l) => l.tier === 'primary');
export const SECONDARY = LISTS.filter((l) => l.tier === 'secondary');

/** Sidebar groups, in order of first appearance. */
export const GROUPS: { label: ListItem['group']; items: ListItem[] }[] = [];
for (const item of LISTS) {
  const g = GROUPS.find((x) => x.label === item.group);
  if (g) g.items.push(item);
  else GROUPS.push({ label: item.group, items: [item] });
}

// In rem, like Tailwind's `sm` and `lg`: a larger browser font size moves the
// breakpoints up with the text, so the top row keeps fitting.
/** Below this the primary lists move to a bottom bar. */
export const PHONE_QUERY = '(width < 40rem)';
/** The sidebar layout only applies from here up. */
export const SIDEBAR_QUERY = '(width >= 64rem)';

export type ShellMode = 'phone' | 'top' | 'sidebar';

/** Which menu the shell shows: the sidebar preference only counts on a wide screen. */
export function shellMode(pref: 'top' | 'sidebar', phone: boolean, wide: boolean): ShellMode {
  if (phone) return 'phone';
  return pref === 'sidebar' && wide ? 'sidebar' : 'top';
}

/**
 * Priority-plus overflow for the secondary items of the top menu.
 *
 * Returns the indices that move into "More". Items collapse from the right; the
 * current one (`current`, -1 if none of these is current) never does.
 *
 * `widths` are the items' full widths (their own padding included, no gap between
 * them), `available` is the room for the whole run, `moreWidth` the "More" button.
 */
export function overflowHidden(widths: number[], available: number, moreWidth: number, current: number): number[] {
  const total = widths.reduce((a, b) => a + b, 0);
  if (total <= available) return [];
  // Something must go, so "More" is showing and takes its share first; then the
  // current item, which stays whatever happens.
  let used = moreWidth + (current >= 0 ? widths[current] : 0);
  const hidden: number[] = [];
  let full = false;
  widths.forEach((w, i) => {
    if (i === current) return;
    if (!full && used + w <= available) used += w;
    else {
      full = true;
      hidden.push(i);
    }
  });
  return hidden;
}
