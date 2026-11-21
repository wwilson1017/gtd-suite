// Notes GTD — the frame around every page: the name, its links, the theme.
import { useEffect, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { ThemeToggle } from '../../core/theme/ThemeToggle';
import { AppBar } from '../todo-gtd/components/AppBar';
import { AppName, Logo } from '../todo-gtd/components/Logo';
import { NextStepButton, SettingsGear } from '../todo-gtd/settings/HeaderSetup';

const navCls = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-lg px-3 py-1.5 font-heading ${isActive ? 'bg-sand text-charcoal' : 'text-muted hover:text-charcoal'}`;

export function NotesShell({ title, children }: { title?: string; children: ReactNode }) {
  const settings = useLocation().pathname.startsWith('/connect');
  useEffect(() => {
    document.title = title ? `${title} · Notes` : 'Notes';
  }, [title]);
  return (
    <div className="min-h-screen bg-sand">
      <AppBar />
      <header className="border-b border-line-faint bg-cream">
        {/* On a phone the links take a row of their own, under the name and the gear. */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2">
          <Link to="/" className="flex items-center gap-2">
            <Logo className="h-7 w-7" />
            <span className="font-heading text-lg font-bold text-charcoal">
              <AppName />
            </span>
          </Link>
          <nav className="order-last flex w-full items-center gap-1 text-sm sm:order-none sm:ml-auto sm:w-auto">
            <NavLink to="/" end className={navCls}>
              Notes
            </NavLink>
            <NavLink to="/archive" className={navCls}>
              Archive
            </NavLink>
          </nav>
          <ThemeToggle className="hidden sm:block" />
          <span className="ml-auto flex items-center gap-2 sm:ml-0">
            <NextStepButton />
            <SettingsGear current={settings} />
          </span>
        </div>
      </header>
      <main className="px-4 pb-16 pt-4">{children}</main>
    </div>
  );
}
