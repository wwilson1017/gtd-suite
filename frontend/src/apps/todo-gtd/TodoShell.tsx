import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMediaQuery, useMenuLayout } from '../../core/theme/menuLayout';
import { AppBar } from './components/AppBar';
import { QuickAdd } from './components/QuickAdd';
import { BottomBar, Sidebar, TopMenu } from './components/ShellMenu';
import { UndoPill } from './components/UndoPill';
import { KeepBanner } from './KeepBanner';
import { PHONE_QUERY, SIDEBAR_QUERY, shellMode, type ListKey } from './menu';
import { todoPath } from './publicMode';
import { NextStepButton, SettingsGear } from './settings/HeaderSetup';
import { useToasts } from './toast';
import { useTodoMeta } from './useTodoMeta';

/** A page's identity for the shell: one of the menu's lists, or Settings ('connect', the
 * gear in the header, not in the menu). The lists themselves are defined in ./menu. */
export type TodoTab = ListKey | 'connect';

interface Props {
  active: TodoTab;
  /** Hide QuickAdd on pages that would fight it with their own form (Review)
   * or that render their own copy lower down the page (Inbox). */
  hideQuickAdd?: boolean;
  onAdded?: () => void;
  /** The page renders <UndoPill inline /> itself (Inbox), so the floating one is left out. */
  inlineUndo?: boolean;
  children: React.ReactNode;
}

/** Shared shell for every todo-gtd page. The app uses flat sibling routes
 * (house style), so this mounts fresh per page — meta comes from the
 * module-level stale-while-revalidate cache in useTodoMeta, which is what
 * keeps the inbox badge from flashing on tab switches. */
export function TodoShell({ active, hideQuickAdd, onAdded, inlineUndo, children }: Props) {
  const { filters, refreshMeta } = useTodoMeta();
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const toasts = useToasts();
  const inboxCount = filters?.status_counts.inbox ?? 0;
  // The list's own name, when it has one, replaces the generic title in the
  // header and in the tab ('Todos' is PublicTodoApp's generic tab title).
  const title = filters?.name || 'Todo GTD';
  const tabTitle = filters?.name || 'Todos';
  useEffect(() => {
    document.title = tabTitle;
  }, [tabTitle]);
  const [layout] = useMenuLayout();
  const mode = shellMode(layout, useMediaQuery(PHONE_QUERY), useMediaQuery(SIDEBAR_QUERY));

  // Keep the header box in sync with ?q= while ON the results page — covers
  // deep links and Back/Forward; elsewhere the box stays a blank launcher.
  // Adjust-during-render (not an effect): re-sync only when the URL value
  // changes, so typing in the box is never clobbered. `active` is the reliable
  // signal — location.pathname carries the router basename.
  const onSearchPage = active === 'search';
  const urlQuery = onSearchPage ? (searchParams.get('q') ?? '') : '';
  // Starts '' (the box's own initial value), not urlQuery: the shell mounts fresh per
  // page, so a deep link's ?q= has to count as a change on the first render too.
  const [prevUrlQuery, setPrevUrlQuery] = useState('');
  if (prevUrlQuery !== urlQuery) {
    setPrevUrlQuery(urlQuery);
    setQuery(urlQuery);
  }

  const menu = { active, inboxCount };

  // The tree keeps one shape in every mode (the sidebar slot is just empty), so
  // resizing across a breakpoint never remounts the page and loses its state. The
  // app bar sits above the page (beside the full-height sidebar, which spans both
  // rows); the sidebar column is empty in the other modes.
  return (
    <div
      className={`grid min-h-screen grid-cols-[auto_minmax(0,1fr)] grid-rows-[auto_1fr] bg-sand ${mode === 'phone' ? 'has-bottom-bar' : ''}`}
    >
      <div className={mode === 'sidebar' ? 'col-start-2 row-start-1' : 'col-span-full'}>
        <AppBar />
      </div>
      {mode === 'sidebar' && (
        <div className="col-start-1 row-span-2 row-start-1">
          <Sidebar {...menu} title={title} />
        </div>
      )}
      {/* `max-w-shell` is the one width cap for header, menu and page (index.css). */}
      <div className="col-start-2 row-start-2 min-w-0">
        <div className="mx-auto max-w-shell px-4 pb-[calc(var(--bottom-bar)+2.5rem)] pt-4">
          <div className="flex items-center gap-3">
            {mode !== 'sidebar' && (
              <h1 className="min-w-0 truncate font-heading text-xl font-bold text-charcoal">{title}</h1>
            )}
            <div className="ml-auto flex items-center gap-2">
              <form
                role="search"
                onSubmit={(e) => {
                  e.preventDefault();
                  navigate(todoPath(`/search?q=${encodeURIComponent(query.trim())}`));
                }}
              >
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search…"
                  aria-label="Search all todos"
                  className="h-10 w-24 sm:w-44 rounded-lg border border-line bg-cream px-3 text-base sm:text-sm text-charcoal placeholder:text-muted focus:border-brand focus:outline-none"
                />
              </form>
              <NextStepButton />
              <SettingsGear current={active === 'connect'} />
            </div>
          </div>

          {/* The list is full: the way to raise its limits. Not on Settings, where the email is. */}
          {active !== 'connect' && <KeepBanner />}

          {mode === 'top' && <TopMenu {...menu} />}

          {!hideQuickAdd && (
            <div className="mt-4">
              <QuickAdd
                onAdded={() => {
                  void refreshMeta();
                  onAdded?.();
                }}
              />
            </div>
          )}

          <div className="mt-5">{children}</div>
        </div>
      </div>

      {mode === 'phone' && <BottomBar {...menu} />}

      {/* ONE bottom stack for both transient surfaces. Two independently
          positioned fixed containers would overlap on a phone, and they co-occur
          by design: undoing a repeating todo fires the reopened-successor toast at
          the moment the undo pill is showing. Stacking them in a single flex column
          makes that impossible by construction, and leaves toasts exactly where
          they were (centered, max-w-sm) while the pill sits bottom-right from `sm`
          up.

          `pointer-events-none` on the full-width wrapper is mandatory: without it
          an invisible bar swallows clicks across the whole viewport. Each child
          opts back in. On a phone the stack sits above the bottom bar. */}
      <div className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--bottom-bar)+1rem)] z-50 flex flex-col items-center gap-2 px-4">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto w-full max-w-sm rounded-xl border px-4 py-2.5 text-sm shadow-lg ${
              t.kind === 'error'
                ? 'border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/80 text-charcoal'
                : 'border-line bg-cream text-charcoal'
            }`}
          >
            {t.text}
          </div>
        ))}
        {!inlineUndo && <UndoPill />}
      </div>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line-faint bg-cream p-8 text-center">
      <p className="font-heading font-semibold text-charcoal">{title}</p>
      {hint && <p className="mt-1 text-sm text-muted">{hint}</p>}
    </div>
  );
}

/** Shown when a client-side filter hides every row of a non-empty list — distinct from the true
 *  empty states above, which mean the LIST is empty. */
export function FilterEmptyState() {
  return (
    <div className="rounded-xl border border-line-faint bg-cream p-8 text-center">
      <p className="text-sm text-muted">No todos match your filter.</p>
    </div>
  );
}

export function LoadingRows() {
  return <p className="py-6 text-center text-sm text-muted">Loading…</p>;
}

export function LoadFailed({ retry }: { retry: () => void }) {
  return (
    <div className="rounded-xl border border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/30 p-4 text-sm text-charcoal">
      Couldn't load todos.{' '}
      <button type="button" onClick={retry} className="underline">
        Retry
      </button>
    </div>
  );
}
