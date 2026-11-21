// The header's side of getting set up (setup.ts), in every app's shell: one button naming
// the next step, gone once every step is done, and the gear that opens Settings.
import { Link } from 'react-router-dom';
import { LABEL, SETTINGS, useSetup, useSetupOnFocus } from './setup';

/** The header's one button: the next step, by name, until every step is done. */
export function NextStepButton() {
  const { next } = useSetup();
  useSetupOnFocus();
  if (!next) return null;
  const [label, short] =
    next.state === 'pending'
      ? ['Check your inbox', 'Check inbox']
      : next.key === 'ai'
        ? [LABEL.ai, 'Connect AI']
        : [LABEL.email, 'Add email'];
  return (
    <Link
      to={`${SETTINGS}/${next.key}`}
      aria-label={label}
      className="flex h-9 flex-none items-center gap-2 whitespace-nowrap rounded-full bg-band-accent px-3 font-heading text-[13px] font-bold text-band shadow-sm hover:brightness-105 sm:px-3.5 sm:text-sm"
    >
      <span aria-hidden="true" className="h-2 w-2 animate-pulse rounded-full bg-band" />
      {/* A phone's header is narrow: the short name there. */}
      <span aria-hidden="true" className="sm:hidden">
        {short}
      </span>
      <span aria-hidden="true" className="hidden sm:inline">
        {label}
      </span>
    </Link>
  );
}

/** Settings, behind an outline gear. */
export function SettingsGear({ current = false }: { current?: boolean }) {
  return (
    <Link
      to={SETTINGS}
      title="Settings"
      aria-label="Settings"
      aria-current={current ? 'page' : undefined}
      className="grid h-10 w-10 flex-none place-items-center rounded-full text-muted hover:bg-charcoal/5 hover:text-charcoal aria-[current=page]:bg-charcoal/5 aria-[current=page]:text-charcoal"
    >
      <svg
        viewBox="0 0 24 24"
        width="22"
        height="22"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </Link>
  );
}
