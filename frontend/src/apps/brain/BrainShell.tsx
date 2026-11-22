// Common Brain — the frame around every page: the suite's app bar, the mark and the
// name, four links, the search box, the next set-up step and the Settings gear. Always
// the Night Network look (index.css html[data-app=brain]). While the box holds a query its results stand in for the page,
// which stays mounted underneath, so a draft being edited survives a search.
import { useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import SearchInput from '../../shared/search/SearchInput';
import { AppBar } from '../todo-gtd/components/AppBar';
import { NextStepButton, SettingsGear } from '../todo-gtd/settings/HeaderSetup';
import { Mark } from './Mark';
import { SearchResults } from './SearchResults';
import './brain.css';
import { BrainSwitcher } from './BrainSwitcher';
import { useBrainSelection } from '../todo-gtd/brainSelection';

const navCls = ({ isActive }: { isActive: boolean }) =>
  `rounded-full px-3 py-1.5 font-heading ${isActive ? 'bg-white/10 text-white' : 'text-muted hover:text-white'}`;

export function BrainShell({ title, children, live = false }: { title?: string; children: ReactNode; live?: boolean }) {
  const { notice } = useBrainSelection();
  const [q, setQ] = useState('');
  // Any move clears the box (a result clears it itself, for the page already open).
  const { pathname } = useLocation();
  const [at, setAt] = useState(pathname);
  if (pathname !== at) {
    setAt(pathname);
    setQ('');
  }
  useEffect(() => {
    document.title = title ? `${title} · Common Brain` : 'Common Brain';
  }, [title]);
  return (
    <div className="cb-app min-h-screen">
      <AppBar />
      <header className="border-b border-white/10">
        <div className="mx-auto flex max-w-shell flex-wrap items-center gap-x-1.5 gap-y-2 px-4 py-2.5 sm:gap-2">
          <Link to="/" className="flex items-center gap-2.5">
            <Mark className="h-8 w-8 text-[#e9ecff]" live={live} small />
            <span className="font-heading text-lg font-bold tracking-tight text-white">Common Brain</span>
          </Link>
          {/* Beside the name on a phone, at the end of the row on anything wider. */}
          <div className="ml-auto flex items-center gap-1.5 sm:order-last sm:ml-0 sm:gap-2">
            <NextStepButton />
            <SettingsGear current={pathname.startsWith('/connect')} />
          </div>
          <BrainSwitcher />
          <SearchInput
            value={q}
            onChange={setQ}
            placeholder="Search your brain"
            className="order-last w-full sm:order-none sm:ml-4 sm:w-auto sm:min-w-32 sm:max-w-56 sm:flex-1"
          />
          <nav className="ml-auto flex flex-wrap items-center gap-1 text-sm">
            <NavLink to="/" end className={navCls}>
              Brain
            </NavLink>
            <NavLink to="/files" className={navCls}>
              Files
            </NavLink>
            <NavLink to="/changes" className={navCls}>
              Changes
            </NavLink>
            <NavLink to="/archive" className={navCls}>
              Archive
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-shell px-4 pb-16 pt-5">
        {notice && (
          <p role="status" className="mb-4 rounded-lg border border-line p-3 text-sm">
            {notice}
          </p>
        )}
        {q.trim() && <SearchResults q={q.trim()} onOpen={() => setQ('')} />}
        <div hidden={!!q.trim()}>{children}</div>
      </main>
    </div>
  );
}
