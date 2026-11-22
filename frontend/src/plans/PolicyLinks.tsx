import { BASE } from '../core/app';
import type { AppConfig } from '../apps/todo-gtd/api';
import { answered, useConfig } from '../apps/todo-gtd/useConfig';
import { EXTRA_POLICIES } from '@extension';

/** The suite's policy pages (static files in public/, served on every app's address).
 *  They describe the hosted service, so a self-hosted (one-list) server shows no links. */
const LINKS: [string, string][] = [
  ['/terms.html', 'Terms'],
  ['/privacy.html', 'Privacy'],
  ['/security.html', 'Security'],
  ['/support.html', 'Support'],
];

export function PolicyLinks({ className = '' }: { className?: string }) {
  return <PolicyNav config={useConfig()} className={className} />;
}

/** The same links for a page that already holds the server's answer, so it asks once. */
export function PolicyNav({ config, className = '' }: { config: AppConfig | null; className?: string }) {
  if (!answered(config) || !config.open_signup) return null; // fail closed: a guess shows nothing
  // An installed extension may add pages of its own while the suite is not free.
  const links = config.free ? LINKS : [...LINKS, ...EXTRA_POLICIES];
  return (
    <nav aria-label="Policies" className={className}>
      {links.map(([href, label], i) => (
        <span key={href}>
          {i > 0 && ' · '}
          <a href={BASE + href} className="underline-offset-2 hover:underline">
            {label}
          </a>
        </span>
      ))}
    </nav>
  );
}
