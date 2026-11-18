// Projects GTD — the frame around every page, shared with Todo GTD:
// the app's name on the left (it opens the jump menu: where to go, and a box to
// jump to a project), search, the notifications bell and the account menu on the
// right, and a row of tabs under it with the open one underlined.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { ThemeToggle } from '../../core/theme/ThemeToggle';
import { AppBar } from '../todo-gtd/components/AppBar';
import { AppName, Logo } from '../todo-gtd/components/Logo';
import { inboxCount, listBoards, listPeople } from './api';
import { NewForYou, useShhh } from './NewForYou';
import { SampleBanner } from './SampleData';
import type { BoardSummary, Person, Project } from './types';
import { Avatar, Menu, ProjectHeader, setMentionNames } from './ui';

// ── The account's people, for every page (avatars, "me", assigning) ──────────

interface PeopleState {
  people: Person[];
  me: Person | null;
  reload: () => void;
}
const PeopleCtx = createContext<PeopleState>({ people: [], me: null, reload: () => {} });

export function PeopleProvider({ children }: { children: ReactNode }) {
  const [people, setPeople] = useState<Person[]>([]);
  const reload = useCallback(() => {
    listPeople().then(
      (list) => {
        setPeople(list);
        setMentionNames(list.map((p) => p.name));
      },
      () => {},
    );
  }, []);
  useEffect(reload, [reload]);
  const me = people.find((p) => p.kind === 'me') ?? null;
  return <PeopleCtx.Provider value={{ people, me, reload }}>{children}</PeopleCtx.Provider>;
}

export const usePeople = () => useContext(PeopleCtx);

// ── The menu behind the name ──────────────────────────────────────────────────

// "Recently visited": the last pages opened in this browser.
const RECENT_KEY = 'bc-recent';
const RECENT_MAX = 8;

function recent(): { path: string; title: string }[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
  } catch {
    return [];
  }
}

function remember(path: string, title: string) {
  if (!title || path === '/') return;
  try {
    localStorage.setItem(
      RECENT_KEY,
      JSON.stringify([{ path, title }, ...recent().filter((r) => r.path !== path)].slice(0, RECENT_MAX)),
    );
  } catch {
    /* fine: a private window keeps none */
  }
}

function UniversalMenu({ onClose }: { onClose: () => void }) {
  const [projects, setProjects] = useState<BoardSummary[]>([]);
  const [q, setQ] = useState('');
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    listBoards().then(setProjects, () => {});
  }, []);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [onClose]);
  const shown = projects.filter((p) => p.name.toLowerCase().includes(q.trim().toLowerCase()));
  const go = (to: string) => {
    onClose();
    navigate(to);
  };
  // Four big tiles (keys 1 to 4), then the rest of the account's pages.
  const tiles: [string, string, string][] = [
    ['Activity', '/activity', '📈'],
    ['Calendar', '/calendar', '📅'],
    ['Reports', '/reports', '📊'],
    ['Everything', '/everything', '🗂️'],
  ];
  const more: [string, string][] = [
    ['My Tasks', '/my/tasks'],
    ['Bookmarks', '/my/bookmarks'],
    ['Timeline', '/lineup'],
    ['People', '/people'],
  ];
  const search = () => go(`/search?q=${encodeURIComponent(q.trim())}`);
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Menu"
      className="absolute left-0 top-12 z-50 w-[min(92vw,640px)] rounded-xl border border-bc-line bg-bc-canvas p-4 shadow-2xl"
    >
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {tiles.map(([label, to, icon], i) => (
          <button
            key={to}
            type="button"
            onClick={() => go(to)}
            className="flex flex-col items-center gap-1 rounded-lg bg-bc-wash px-2 py-3 text-sm font-semibold hover:bg-bc-line"
          >
            <span aria-hidden className="text-xl">
              {icon}
            </span>
            {label}
            <kbd className="text-[11px] font-normal text-bc-subtle">{i + 1}</kbd>
          </button>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm">
        {more.map(([label, to]) => (
          <button key={to} type="button" className="text-bc-blue hover:underline" onClick={() => go(to)}>
            {label}
          </button>
        ))}
      </div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        autoFocus
        placeholder="Search or jump to a project…"
        aria-label="Search or jump to a project"
        className="bc-input mt-3"
        onKeyDown={(e) => {
          if (e.key !== 'Enter' || !q.trim()) return;
          const exact = shown.find((p) => p.name.toLowerCase() === q.trim().toLowerCase());
          if (exact) go(`/p/${exact.id}`);
          else search();
        }}
      />
      {q.trim() && (
        <button
          type="button"
          onClick={search}
          className="mt-2 flex w-full items-center gap-2 rounded-full px-3 py-1.5 text-left hover:bg-bc-wash"
        >
          <span aria-hidden>🔎</span>
          <span className="truncate">Search everything for “{q.trim()}”</span>
        </button>
      )}
      {!q.trim() && recent().length > 0 && (
        <>
          <p className="mt-3 text-xs font-bold uppercase tracking-wide text-bc-subtle">Recently visited</p>
          <ul className="mt-1">
            {recent().map((r) => (
              <li key={r.path}>
                <button
                  type="button"
                  onClick={() => go(r.path)}
                  className="flex w-full items-center gap-2 rounded-full px-3 py-1 text-left text-sm hover:bg-bc-wash"
                >
                  <span aria-hidden>🕘</span>
                  <span className="truncate">{r.title}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-3 text-xs font-bold uppercase tracking-wide text-bc-subtle">Projects</p>
      <ul className="mt-1 max-h-64 overflow-y-auto">
        {shown.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => go(`/p/${p.id}`)}
              className="flex w-full items-center gap-2 rounded-full px-3 py-1.5 text-left hover:bg-bc-wash"
            >
              <span aria-hidden>📁</span>
              <span className="truncate">{p.name}</span>
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="px-3 py-1.5 text-sm text-bc-subtle">No project by that name.</li>}
      </ul>
      <div className="mt-3 flex items-center gap-3 border-t border-bc-line pt-3 text-sm">
        <button type="button" className="text-bc-blue underline" onClick={() => go('/ai')}>
          Connect your AI
        </button>
        <button type="button" className="text-bc-blue underline" onClick={() => go('/people')}>
          People
        </button>
        <ThemeToggle className="ml-auto" />
      </div>
    </div>
  );
}

// ── The frame ─────────────────────────────────────────────────────────────────

const tabCls = ({ isActive }: { isActive: boolean }) =>
  `-mb-px whitespace-nowrap border-b-2 px-2.5 py-2 text-[15px] ${isActive ? 'border-bc-blue font-bold text-bc-ink' : 'border-transparent text-bc-subtle hover:text-bc-ink'}`;
const sideCls = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap px-1.5 py-2 text-[13px] ${isActive ? 'font-bold text-bc-ink' : 'text-bc-subtle hover:text-bc-ink'}`;

// Keys: Shift and a letter for a place; 1 Activity, 2 Calendar, 3 Reports, 4 Everything.
const SHIFT_KEYS: Record<string, string> = {
  H: '/',
  T: '/my/tasks',
  B: '/my/bookmarks',
  W: '/my/drafts',
  O: '/my/boosts',
  Y: '/activity?person=me',
};

/** `project`: the page is one of that project's tabs, so its header and tabs go on top. */
export function ProjectsShell({
  title,
  project,
  children,
}: {
  title?: string;
  project?: Project | null;
  children: ReactNode;
}) {
  const [menu, setMenu] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const [unread, setUnread] = useState(0);
  const [quiet, setQuiet] = useShhh();
  const { me } = usePeople();
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    document.title = `${unread && !quiet ? `(${unread}) ` : ''}${title ? `${title} · Projects GTD` : 'Projects GTD'}`;
  }, [title, unread, quiet]);
  useEffect(() => {
    remember(location.pathname + location.search, title ?? '');
  }, [title, location.pathname, location.search]);
  // The unread count on the bell: on every page, and every minute.
  useEffect(() => {
    const check = () => {
      inboxCount().then(setUnread, () => {});
    };
    check();
    const timer = window.setInterval(check, 60_000);
    return () => window.clearInterval(timer);
  }, [location.pathname]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || t.closest('input, textarea, select, [contenteditable]')) return;
      if (!e.shiftKey && e.key === '1') {
        navigate('/activity');
        return;
      }
      if (!e.shiftKey && e.key === '2') {
        navigate('/calendar');
        return;
      }
      if (!e.shiftKey && e.key === '3') {
        navigate('/reports');
        return;
      }
      if (!e.shiftKey && e.key === '4') {
        navigate('/everything');
        return;
      }
      if (!e.shiftKey) return;
      if (e.key === 'J') {
        e.preventDefault();
        setMenu((m) => !m);
      }
      if (e.key === 'S') {
        e.preventDefault();
        setSidebar((s) => !s);
      }
      if (SHIFT_KEYS[e.key]) {
        e.preventDefault();
        navigate(SHIFT_KEYS[e.key]);
      }
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [navigate]);
  const [q, setQ] = useState('');
  return (
    <div className="bc min-h-screen">
      <AppBar />
      <header className="relative mx-auto max-w-[1400px] px-4 pt-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setMenu((m) => !m)}
            aria-expanded={menu}
            aria-haspopup="dialog"
            title="Jump to… (Shift+J)"
            className="-ml-2 flex items-center gap-1.5 rounded-lg px-2 py-1.5 hover:bg-bc-wash"
          >
            <Logo app="projects" className="h-6 w-6" />
            <span className="text-xl font-bold">
              <AppName app="projects" />
            </span>
            <span aria-hidden className="text-bc-subtle">
              ⌄
            </span>
          </button>
          {menu && <UniversalMenu onClose={() => setMenu(false)} />}
          <form
            role="search"
            className="ml-auto hidden sm:block"
            onSubmit={(e) => {
              e.preventDefault();
              if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`);
            }}
          >
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search…"
              aria-label="Search everything"
              className="bc-input w-56 py-1.5 text-[14px]"
            />
          </form>
          <button
            type="button"
            onClick={() => setSidebar((s) => !s)}
            aria-expanded={sidebar}
            aria-label={`Notifications${unread ? `: ${unread} unread` : ''}`}
            title="Notifications"
            className="relative ml-auto flex h-10 w-10 items-center justify-center rounded-lg border border-bc-line bg-bc-canvas text-lg hover:bg-bc-wash sm:ml-0"
          >
            <span aria-hidden>🔔</span>
            {unread > 0 &&
              (quiet ? (
                <span title="Quiet until tomorrow" aria-hidden className="absolute -right-1.5 -top-1.5 text-sm">
                  🤫
                </span>
              ) : (
                <span className="absolute -right-1.5 -top-1.5 min-w-5 rounded-full bg-bc-unread px-1 text-center text-[11px] font-bold leading-5 text-white">
                  {unread}
                </span>
              ))}
          </button>
          <Menu
            label="My account"
            items={[
              { label: 'My Activity (Shift+Y)', onClick: () => navigate('/activity?person=me') },
              { label: 'My Drafts (Shift+W)', onClick: () => navigate('/my/drafts') },
              { label: 'My Reactions (Shift+O)', onClick: () => navigate('/my/boosts') },
              { label: 'My Bookmarks (Shift+B)', onClick: () => navigate('/my/bookmarks') },
              'sep',
              { label: 'People', onClick: () => navigate('/people') },
              { label: 'Connect your AI', onClick: () => navigate('/ai') },
              { label: 'Settings', onClick: () => navigate('/connect') },
            ]}
          />
          {me && (
            <span className="hidden sm:block">
              <Avatar person={me} size={32} />
            </span>
          )}
        </div>
        <nav aria-label="Pages" className="mt-1 flex items-end overflow-x-auto border-b border-bc-line">
          <NavLink to="/" end className={tabCls}>
            Projects
          </NavLink>
          <NavLink to="/my/tasks" className={tabCls}>
            My Tasks
          </NavLink>
          <NavLink to="/calendar" className={tabCls}>
            Calendar
          </NavLink>
          <NavLink to="/activity" className={tabCls}>
            Activity
          </NavLink>
          <NavLink to="/reports" className={tabCls}>
            Reports
          </NavLink>
          <span className="ml-auto flex items-center pl-4">
            <NavLink to="/my/bookmarks" className={sideCls}>
              Bookmarks
            </NavLink>
            <NavLink to="/everything" className={sideCls}>
              Everything
            </NavLink>
            <NavLink to="/people" className={sideCls}>
              People
            </NavLink>
            <NavLink to="/ai" className={sideCls}>
              Your AI
            </NavLink>
            <NavLink to="/connect" className={sideCls}>
              Settings
            </NavLink>
          </span>
        </nav>
      </header>
      <main className="mx-auto max-w-[1400px] px-2 pb-10 pt-4 sm:px-4">
        <SampleBanner />
        {project && <ProjectHeader project={project} />}
        {children}
      </main>
      {sidebar && <NewForYou onClose={() => setSidebar(false)} onCount={setUnread} quiet={quiet} setQuiet={setQuiet} />}
    </div>
  );
}
