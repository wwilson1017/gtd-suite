import { ThemeToggle } from '../../../core/theme/ThemeToggle';
import { PolicyLinks } from '../../../plans/PolicyLinks';
import { AppName, Logo } from './Logo';

/** The plain page chrome for everything outside a list's shell: landing, sign-in,
 *  and the app's own "could not load" message.
 *  `wide` is the landing page's intro, which needs room for the phone beside the text. */
export function PageFrame({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="min-h-screen bg-sand">
      <main className={`mx-auto px-4 pb-10 pt-8 ${wide ? 'max-w-shell' : 'max-w-xl'}`}>
        <div className="mb-5 flex items-center gap-3">
          <Logo className="h-8 w-8" />
          <span className="font-heading text-xl font-bold text-charcoal">
            <AppName />
          </span>
          <ThemeToggle className="ml-auto" />
        </div>
        {children}
        <PolicyLinks className="mt-8 text-center text-xs text-muted" />
      </main>
    </div>
  );
}
