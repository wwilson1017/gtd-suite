// Notes GTD — the frame around every page: the name, three links, the theme.
import { useEffect, type ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { ThemeToggle } from '../../core/theme/ThemeToggle';
import { AppBar } from '../todo-gtd/components/AppBar';
import { AppName, Logo } from '../todo-gtd/components/Logo';

const navCls = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-1.5 font-heading ${isActive ? 'bg-sand text-charcoal' : 'text-muted hover:text-charcoal'}`;

export function NotesShell({ title, children }: { title?: string; children: ReactNode }) {
  useEffect(() => {
    document.title = title ? `${title} · Notes` : 'Notes';
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
              Notes
            </NavLink>
            <NavLink to="/archive" className={navCls}>
              Archive
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
