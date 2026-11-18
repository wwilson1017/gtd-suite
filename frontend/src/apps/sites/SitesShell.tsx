// Simple Sites — the frame around every page: the name, two links, the theme.
// simplification: a copy of ProjectsShell with its own name and links; share one
// shell once a third app needs the same frame.
import { useEffect, type ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { ThemeToggle } from '../../core/theme/ThemeToggle';
import { AppBar } from '../todo-gtd/components/AppBar';
import { AppName, Logo } from '../todo-gtd/components/Logo';

const navCls = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-1.5 font-heading ${isActive ? 'bg-sand text-charcoal' : 'text-muted hover:text-charcoal'}`;

export function SitesShell({ title, children }: { title?: string; children: ReactNode }) {
  useEffect(() => {
    document.title = title ? `${title} · Sites` : 'Sites';
  }, [title]);
  return (
    <div className="min-h-screen bg-sand">
      <AppBar />
      <header className="border-b border-line-faint bg-cream">
        <div className="flex items-center gap-2 px-4 py-2">
          <Link to="/" className="flex items-center gap-2">
            <Logo className="h-7 w-7" />
            <span className="font-heading text-lg font-bold text-charcoal">
              <AppName />
            </span>
          </Link>
          <nav className="ml-auto flex items-center gap-1 text-sm">
            <NavLink to="/" end className={navCls}>
              Sites
            </NavLink>
            <NavLink to="/connect" className={navCls}>
              Connect
            </NavLink>
          </nav>
          <ThemeToggle className="hidden sm:block" />
        </div>
      </header>
      <main className="px-4 pb-16 pt-4">{children}</main>
    </div>
  );
}
