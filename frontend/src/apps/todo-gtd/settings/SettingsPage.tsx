// Settings, the same in every app but Common Brain, inside each app's own shell and
// colours: a menu of sections in groups (Get started, Account, and the app's own), each
// section at its own address, /connect/<key>. On a phone the menu is a list that opens
// one section at a time, with "‹ Settings" back. Until every setup step is done
// (setup.tsx), a two-step box in the app's band colours sits above the open section.
// /connect alone opens the first step still to do (on a phone: the menu); the old
// /connect#email lands on the email.
import { Fragment } from 'react';
import { Link, Navigate, useLocation, useParams } from 'react-router-dom';
import { APP } from '../../../core/app';
import { useMediaQuery } from '../../../core/theme/menuLayout';
import { usePlanSection } from '../../../paid/planSection';
import { reachOf } from '../clients';
import { AccountNumber, EmailSection, SignInElsewhere, ThisDevice } from '../ConnectPage';
import { ConnectAI } from '../components/ConnectAI';
import { InstallGuide } from '../components/InstallGuide';
import { OtherApps } from '../components/OtherApps';
import { useSession } from '../session';
import { hasOtherApps, useConfig } from '../useConfig';
import { LABEL, SETTINGS, useSetup, type Section, type Step, type StepKey } from './setup';

/** An app's own group of sections, after Account (Todo GTD's). */
export interface Group {
  title: string;
  sections: Section[];
}

const PHONE = '(width < 48rem)';
/** Where "Skip for now" goes, in each app's words. */
const HOME: Record<string, string> = {
  todo: 'my list',
  notes: 'my notes',
  projects: 'my projects',
  sites: 'my pages',
  brain: 'my brain',
};
const STEP_SUB: Record<StepKey, string> = {
  ai: 'Paste one link into ChatGPT, Claude or any AI.',
  email: 'Keep everything and sign in anywhere. One link, no password.',
};

function useGroups(own?: Group): Group[] {
  const session = useSession().session;
  const config = useConfig();
  const plan = usePlanSection();
  const reaches = reachOf(session?.apps ?? []) || 'apps';
  const start: Section[] = [
    {
      key: 'ai',
      icon: '✦',
      title: LABEL.ai,
      sub: `One link lets ChatGPT, Claude or any AI read, add and update your ${reaches}. It can never delete.`,
      body: <ConnectAI />,
    },
  ];
  if (session?.mail) {
    start.push({
      key: 'email',
      icon: '✉',
      title: LABEL.email,
      sub: 'Keep your account for good and sign in on any device.',
      body: <EmailSection />,
    });
  }
  const account: Section[] = [
    ...(plan ? [plan] : []),
    {
      key: 'devices',
      icon: '⌁',
      title: 'Devices & sign-in',
      sub: 'Sign in on another device, or sign out.',
      body: (
        <div className="space-y-4">
          <SignInElsewhere />
          <ThisDevice />
          <AccountNumber />
        </div>
      ),
    },
    ...(hasOtherApps(config)
      ? [
          {
            key: 'apps',
            icon: '▦',
            title: 'Your apps',
            sub: 'One account and one agent link for all of them.',
            body: <OtherApps titled={false} />,
          },
        ]
      : []),
    {
      key: 'install',
      icon: '⌂',
      title: 'Install on your phone',
      sub: 'Opens full screen, like an app from the store.',
      body: <InstallGuide />,
    },
  ];
  return [{ title: 'Get started', sections: start }, { title: 'Account', sections: account }, ...(own ? [own] : [])];
}

export function SettingsPage({ group }: { group?: Group }) {
  const { section } = useParams();
  const { hash, search } = useLocation();
  const phone = useMediaQuery(PHONE);
  const setup = useSetup();
  const groups = useGroups(group);
  const welcome = new URLSearchParams(search).has('welcome');

  if (!section && hash === '#email') return <Navigate to={`${SETTINGS}/email`} replace />;
  const all = groups.flatMap((g) => g.sections);
  const asked = all.find((s) => s.key === section);
  // A section not here (yet: the plan waits for the server's answer) opens the default.
  const open = asked ?? all.find((s) => s.key === (setup.next?.key ?? 'ai'))!;
  const menuOnly = phone && !asked;

  const badge = (key: string) => {
    const step = setup.steps.find((s) => s.key === key);
    return step ? <Badge step={step} n={setup.steps.indexOf(step) + 1} /> : null;
  };

  return (
    <div className="mx-auto max-w-5xl">
      {menuOnly && <SetupBox welcome={welcome} />}
      <div className="md:grid md:grid-cols-[18rem_minmax(0,1fr)] md:items-start md:gap-8">
        {(!phone || menuOnly) && (
          <nav
            aria-label="Settings"
            className={
              phone
                ? 'rounded-2xl border border-line-faint bg-cream p-2'
                : 'sticky top-4 flex flex-col gap-0.5 rounded-2xl'
            }
          >
            {groups.map((g) => (
              <Fragment key={g.title}>
                <p className="mx-2.5 mb-1 mt-4 text-[11px] font-bold uppercase tracking-wider text-muted first:mt-1">
                  {g.title}
                </p>
                {g.sections.map((s) => {
                  const current = !phone && s.key === open.key;
                  return (
                    <Link
                      key={s.key}
                      to={`${SETTINGS}/${s.key}`}
                      aria-current={current ? 'page' : undefined}
                      className={`flex w-full items-center gap-2.5 whitespace-nowrap rounded-lg px-2.5 text-sm text-charcoal ${
                        phone ? 'py-3' : 'py-2'
                      } ${current ? 'bg-cream font-bold shadow-sm ring-1 ring-line-faint' : 'hover:bg-charcoal/5'}`}
                    >
                      <span aria-hidden="true" className="w-5 flex-none text-center text-brand-ink">
                        {s.icon}
                      </span>
                      <span className="min-w-0 truncate">{s.title}</span>
                      <span className="ml-auto flex items-center text-muted">
                        {badge(s.key) ?? (phone && <span aria-hidden="true">›</span>)}
                      </span>
                    </Link>
                  );
                })}
              </Fragment>
            ))}
          </nav>
        )}
        {!menuOnly && (
          <section aria-labelledby="settings-section" className="min-w-0">
            {phone && (
              <Link to={SETTINGS} className="mb-3 inline-block font-heading text-sm font-semibold text-brand-ink">
                ‹ Settings
              </Link>
            )}
            {/* On a phone only above the two steps' own sections: elsewhere it would bury the page. */}
            {(!phone || open.key === 'ai' || open.key === 'email') && <SetupBox welcome={welcome} />}
            <h2 id="settings-section" className="font-heading text-2xl font-extrabold tracking-tight text-charcoal">
              {open.title}
            </h2>
            <p className="mb-4 mt-0.5 text-sm text-muted">{open.sub}</p>
            {open.body}
          </section>
        )}
      </div>
    </div>
  );
}

function Badge({ step, n }: { step: Step; n: number }) {
  const [text, cls] =
    step.state === 'done'
      ? ['Done', 'bg-green-50 text-green-800 dark:bg-green-950/50 dark:text-green-300']
      : step.state === 'pending'
        ? ['Check inbox', 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300']
        : [`Step ${n}`, 'bg-brand/10 text-brand-ink'];
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-extrabold uppercase tracking-wide ${cls}`}>
      {text}
    </span>
  );
}

/** The steps still to do, in the app's band colours; gone once every one is done.
 *  `welcome`: a brand-new account's first visit, which may skip ahead to the app. */
function SetupBox({ welcome }: { welcome: boolean }) {
  const { steps, next } = useSetup();
  if (!next) return null;
  const done = steps.filter((s) => s.state === 'done').length;
  const progress = ((done + (next.state === 'pending' ? 0.5 : 0)) / steps.length) * 100;
  return (
    <section
      aria-label="Get set up"
      className="mb-6 rounded-2xl bg-linear-135 from-band to-brand-deep p-5 text-white shadow-md"
    >
      <h2 className="font-heading text-xl font-bold">
        {steps.length === 1 ? 'One step to go' : 'Get set up in two steps'}
      </h2>
      <p className="mt-0.5 text-sm text-band-text">About two minutes. Your AI does the rest.</p>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/20">
        <div className="h-full rounded-full bg-band-accent transition-[width]" style={{ width: `${progress}%` }} />
      </div>
      <p className="mt-1 text-xs text-band-text">
        {done} of {steps.length} done
      </p>
      {steps.map((s, i) => {
        const current = s === next;
        return (
          <Link
            key={s.key}
            to={`${SETTINGS}/${s.key}`}
            className={`mt-2.5 flex items-center gap-3.5 rounded-xl border-2 bg-cream p-3.5 text-left text-charcoal ${
              current ? 'border-band-accent shadow-sm' : 'border-transparent opacity-65 hover:opacity-90'
            }`}
          >
            <span
              aria-hidden="true"
              className={`grid h-8 w-8 flex-none place-items-center rounded-full font-heading font-extrabold ${
                s.state === 'done'
                  ? 'bg-green-50 text-green-700 dark:bg-green-950/50 dark:text-green-300'
                  : s.state === 'pending'
                    ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                    : 'bg-brand/10 text-brand-ink'
              }`}
            >
              {s.state === 'done' ? '✓' : s.state === 'pending' ? '…' : i + 1}
            </span>
            <span className="min-w-0">
              <span className="block font-heading font-bold">{LABEL[s.key]}</span>
              <span className="block text-sm text-muted">
                {s.state === 'pending' ? 'Check your inbox for the link.' : STEP_SUB[s.key]}
              </span>
            </span>
            <span
              aria-hidden="true"
              className={`ml-auto flex-none rounded-lg px-3.5 py-2 font-heading text-sm font-bold ${
                current ? 'bg-brand-dark text-white' : 'border border-line'
              }`}
            >
              {s.state === 'done' ? 'View' : s.state === 'pending' ? 'Open' : 'Start'}
            </span>
          </Link>
        );
      })}
      {welcome && (
        <Link
          to="/"
          className="mx-auto mt-3 block w-fit text-sm text-band-text underline underline-offset-2 hover:text-white"
        >
          Skip for now, go to {HOME[APP] ?? 'the app'} →
        </Link>
      )}
    </section>
  );
}
