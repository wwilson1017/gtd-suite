import { offersPlans } from '../../paid/features';
// The landing page (/): make a list, or sign in to one you have. Todo GTD's own is
// front/TodoFront; the other apps share FrontDoor below.
import { lazy, Suspense, useId, useState, type ReactNode } from 'react';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { BASE, APP } from '../../core/app';
import { firstPage } from './settings/setup';
import { createList, requestSignIn, resetAccess } from './api';
import { Logo } from './components/Logo';
import { PageFrame } from './components/PageFrame';
import { useConfig } from './useConfig';

const ProjectsDemo = lazy(() => import('../projects-gtd/ProjectsDemo').then((m) => ({ default: m.ProjectsDemo })));
const NotesDemo = lazy(() => import('../notes-gtd/NotesDemo').then((m) => ({ default: m.NotesDemo })));
const SitesPlans = lazy(() => import('../../paid/SitesPlans').then((m) => ({ default: m.SitesPlans })));
const BrainLanding = lazy(() => import('../brain/BrainLanding').then((m) => ({ default: m.BrainLanding })));
const SitesDemo = lazy(() => import('../sites/SitesDemo').then((m) => ({ default: m.SitesDemo })));
const TodoFront = lazy(() => import('./front/TodoFront').then((m) => ({ default: m.TodoFront })));

const inputCls =
  'min-w-0 flex-1 rounded-lg border border-line bg-cream px-3 py-2 text-base sm:text-sm text-charcoal focus:border-brand focus:outline-none';
const secondaryBtn =
  'shrink-0 rounded-lg border border-line bg-cream px-3 py-2 text-sm font-heading text-charcoal hover:bg-sand disabled:opacity-40';

/** The browser's IANA zone — the list's "today" follows it (changeable later in Settings). */
function browserTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Into the app. replace(), not assign(): Back must not return to a form already used.
 *  A brand-new account opens once on Settings › Connect your AI, which can skip ahead.
 *  Common Brain opens Home (settings/setup.ts firstPage). */
function openApp(welcome = false) {
  window.location.replace(BASE + firstPage(APP, welcome));
}

/** `account`: call what the person has an account, not a list (Notes). */
function SignIn({ account = false }: { account?: boolean }) {
  const aList = account ? 'an account' : 'a list';
  const emailId = useId();
  const [email, setEmail] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');

  const send = async () => {
    if (!email.trim() || state === 'sending') return;
    setState('sending');
    try {
      await requestSignIn(email.trim());
      setState('sent');
    } catch {
      setState('error');
    }
  };

  return (
    <details className="mt-8 rounded-xl border border-line-faint bg-cream p-4">
      <summary className="cursor-pointer text-sm font-heading font-semibold text-charcoal">
        Already have {aList}? Sign in
      </summary>
      <form
        className="mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <label htmlFor={emailId} className="block text-sm text-charcoal">
          The email on your {account ? 'account' : 'list'}
        </label>
        <div className="mt-1 flex items-center gap-2">
          <input
            id={emailId}
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setState('idle');
            }}
            placeholder="you@example.com"
            className={inputCls}
          />
          <button type="submit" disabled={!email.trim() || state === 'sending'} className={secondaryBtn}>
            Email me a link
          </button>
        </div>
        <p role="status" className="mt-2 text-sm text-muted">
          {state === 'sent' &&
            `If ${aList} uses that address, a sign-in link is on its way. It works once, for one hour.`}
          {state === 'error' && (
            <span className="text-brand-ink">Could not send right now — try again in a minute.</span>
          )}
        </p>
      </form>
    </details>
  );
}

/** One-list servers: the operator's way back in. Posts the reset code; the server
 *  signs every browser out, replaces the agent and capture links, and signs this
 *  browser in. */
function ResetAccess() {
  const codeId = useId();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const reset = async () => {
    if (!code || busy) return;
    setBusy(true);
    setError('');
    try {
      await resetAccess(code);
      openApp();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not reset access. Try again.'));
      setBusy(false);
    }
  };

  return (
    <details className="mt-8 rounded-xl border border-line-faint bg-cream p-4">
      <summary className="cursor-pointer text-sm font-heading font-semibold text-charcoal">Reset access</summary>
      <form
        className="mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          void reset();
        }}
      >
        <p className="text-sm text-charcoal">
          This signs every browser out of the list, removes its email, and replaces its agent and capture links &mdash;
          then signs this browser in. The todos are untouched.
        </p>
        <label htmlFor={codeId} className="mt-2 block text-sm text-charcoal">
          Reset code <span className="text-muted">(the server&rsquo;s RESET_CODE setting)</span>
        </label>
        <div className="mt-1 flex items-center gap-2">
          <input
            id={codeId}
            type="password"
            required
            autoComplete="off"
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
              setError('');
            }}
            className={inputCls}
          />
          <button type="submit" disabled={!code || busy} className={secondaryBtn}>
            {busy ? 'Working…' : 'Reset access'}
          </button>
        </div>
        {error && (
          <p role="alert" className="mt-2 text-sm text-brand-ink">
            {error}
          </p>
        )}
      </form>
    </details>
  );
}

/** For a browser that is signed in but landed here anyway (the dev server, or a
 *  page the server does not redirect). */
function OpenMyList({ onBand = false, what = 'list' }: { onBand?: boolean; what?: string }) {
  return (
    <p className="mt-4 text-sm">
      <a
        href={BASE + '/app'}
        className={`font-heading font-semibold underline ${onBand ? 'text-white' : 'text-brand-ink'}`}
      >
        Open my {what}
      </a>
      <span className={onBand ? '' : 'text-muted'}>
        {' '}
        &mdash; this browser is signed in{what === 'list' ? ' to one' : ''}.
      </span>
    </p>
  );
}

/** The intro, beside the phone. */
const NOTE_POINTS = [
  [
    'Your AI saves, you read',
    'Give your AI its link and ask it to keep a note. Each one lands here as a card that says which AI saved it, and when.',
  ],
  [
    'Small edits, nothing lost',
    'Fix a word, tick a box, pin what matters. If your AI changes a note while you are editing it, you choose which to keep.',
  ],
  ['Find it when you need it', 'Search every note, or tap a #tag your AI added.'],
];

/** Projects' intro, beside its phone. */
const PROJECT_POINTS = [
  [
    'Your AI is on the team',
    'Give your AI its link once. Then ask it to add cards, move them along, tick off a checklist or leave a comment. Everything it does carries its own name.',
  ],
  [
    'Cards hold the work',
    'Labels, due dates, checklists, people and notes on every card. When the work moves on, drag the card to the next column.',
  ],
  [
    'More than a board when you need it',
    'Turn on messages, to-dos, docs, a schedule or check-ins beside the board, one project at a time.',
  ],
  [
    'Starts with a sample',
    'Your first look has sample projects to try things on. One button puts them away when you are ready.',
  ],
];

/** Sites' intro, beside its phone. */
const SITE_POINTS = [
  [
    'One step from your AI',
    'Give your AI its link once. After that, \u201cput this on the web\u201d is all it takes: it publishes the page and hands you the address.',
  ],
  [
    'Fine to throw away',
    'AI writes a web app in minutes, so it can be disposable. Park it here while you need it, then take it down.',
  ],
  [
    'More than a chat, short of a .com',
    'It outlasts the chat it was made in, and anyone with the address can open it. When it gets serious, buy a domain; until then, it lives here.',
  ],
  [
    'Change it, keep the link',
    'Ask your AI for an edit and the same address shows the new version. Nobody needs a new link.',
  ],
  [
    'Unlisted, with short links too',
    'Pages are never indexed: only people with the address can open them. Turn any long web address into a short one, too.',
  ],
];

export function LandingPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The server said so on a create (409): someone else claimed the list first.
  const [taken, setTaken] = useState(false);
  const [name, setName] = useState('');
  const config = useConfig();
  const mail = config?.mail === true;

  const create = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await createList(browserTz(), name.trim());
      openApp(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && !config?.open_signup) setTaken(true);
      else setError(apiErrorMessage(e, 'Could not create a list. Try again.'));
      setBusy(false);
    }
  };

  if (taken || config?.claimed) {
    return (
      <PageFrame>
        <h1 className="font-heading text-3xl font-bold text-charcoal">This list is set up</h1>
        <p className="mt-3 text-charcoal">
          This server holds one todo list, and it has already been created. Open it on a device that is signed in: in
          Settings, it can make a sign-in link for this one.
          {mail && ' Or sign in with the email on the list.'}
        </p>
        {config?.signed_in && <OpenMyList />}
        {mail && <SignIn />}
        {config?.reset ? (
          <ResetAccess />
        ) : (
          <p className="mt-3 text-sm text-muted">
            Locked out? Whoever runs this server can set a <code>RESET_CODE</code> variable on it; this page then offers
            a way back in.
          </p>
        )}
      </PageFrame>
    );
  }

  if (APP === 'brain') {
    return (
      <Suspense fallback={null}>
        <BrainLanding
          onStart={() => void create()}
          busy={busy}
          ready={!!config}
          error={error}
          signedIn={config?.signed_in === true}
          apps={config?.apps ?? {}}
          config={config}
          signIn={mail && <SignIn account />}
        />
      </Suspense>
    );
  }

  if (APP === 'notes') {
    return (
      <FrontDoor
        title="See the notes your AI saves"
        lead={
          <>
            Claude, ChatGPT or any other AI tool saves notes here as it works: research, meeting notes, plans, lists.
            Open them like any notes app, read what you need, and fix a line or tick a box.
          </>
        }
        points={NOTE_POINTS}
        partOf={config?.apps.todo?.url}
        footnote={
          <>
            Already use Todo GTD? Notes is a tab at the top there: the same account and the same agent link. Nothing is
            ever deleted: notes are archived, and you can bring them back.
          </>
        }
        demo={
          <Suspense fallback={null}>
            <NotesDemo />
          </Suspense>
        }
        signIn={mail && <SignIn account />}
      >
        {config?.signed_in && <OpenMyList onBand what="notes" />}
        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
          <button type="button" onClick={() => void create()} disabled={busy || !config} className={bandBtn}>
            {busy ? 'Setting up…' : 'Start my notes'}
          </button>
          <span className="text-sm">No sign-up. No password.</span>
        </div>
        {error && (
          <p role="alert" className="mt-3 text-sm text-band-accent">
            {error}
          </p>
        )}
      </FrontDoor>
    );
  }

  if (APP === 'projects') {
    return (
      <FrontDoor
        title="A simple kanban board you and your AI both work on"
        lead={
          <>
            Every project is a board of cards you move from column to column. Claude, ChatGPT or any other AI tool works
            on it with you: it adds cards, moves them along and comments.
          </>
        }
        points={PROJECT_POINTS}
        partOf={config?.apps.todo?.url}
        footnote={
          <>
            Already use Todo GTD, Notes or Sites? It is the same account and the same agent link: open Projects from
            there. Nothing is ever deleted: cards and projects are archived, and you can bring them back.
          </>
        }
        demo={
          <Suspense fallback={null}>
            <ProjectsDemo />
          </Suspense>
        }
        signIn={mail && <SignIn account />}
      >
        {config?.signed_in && <OpenMyList onBand what="projects" />}
        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
          <button type="button" onClick={() => void create()} disabled={busy || !config} className={bandBtn}>
            {busy ? 'Setting up…' : 'Start my projects'}
          </button>
          <span className="text-sm">No sign-up. No password.</span>
        </div>
        {error && (
          <p role="alert" className="mt-3 text-sm text-band-accent">
            {error}
          </p>
        )}
      </FrontDoor>
    );
  }

  if (APP === 'sites') {
    const host = config?.sites_short_host || window.location.host;
    return (
      <FrontDoor
        title="Park what your AI makes. Share it with one link."
        lead={
          <>
            A demo, a report, research, a quick web app: Claude, ChatGPT or any other AI tool puts it on the web in one
            step, at a short address like{' '}
            <span className="font-semibold text-white [overflow-wrap:anywhere]">{host}/split-k7Qm2xPa9R</span>. Anyone
            with the address can open it, no login needed.
          </>
        }
        points={SITE_POINTS}
        eyebrow={offersPlans(config) ? 'Free to start \u00b7 one click \u00b7 nothing to install' : undefined}
        footnote={
          <>
            {!offersPlans(config) &&
              'Free to start: one site to try for 7 days, then 500 pages and 500 short links once you confirm an email. '}
            Already use Todo GTD, Notes GTD or Projects GTD? It is the same account and the same agent link: open Sites
            from there.
          </>
        }
        demo={
          <Suspense fallback={null}>
            <SitesDemo host={host} />
          </Suspense>
        }
        signIn={
          <>
            {offersPlans(config) && (
              <Suspense fallback={null}>
                <SitesPlans />
              </Suspense>
            )}
            {mail && <SignIn account />}
          </>
        }
      >
        {config?.signed_in && <OpenMyList onBand what="sites" />}
        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
          <button type="button" onClick={() => void create()} disabled={busy || !config} className={bandBtn}>
            {busy ? 'Setting up…' : 'Start my sites'}
          </button>
          <span className="text-sm">No sign-up. No password.</span>
        </div>
        {error && (
          <p role="alert" className="mt-3 text-sm text-band-accent">
            {error}
          </p>
        )}
      </FrontDoor>
    );
  }

  return (
    <Suspense fallback={null}>
      <TodoFront
        config={config}
        busy={busy}
        error={error}
        name={name}
        onName={setName}
        onStart={() => void create()}
        signIn={mail && <SignIn />}
      />
    </Suspense>
  );
}

const bandBtn =
  'rounded-lg bg-white px-6 py-3 font-heading text-lg font-semibold text-band hover:bg-band-hover disabled:opacity-40';

/** An app's front door: the band with its pitch, its points and a working demo
 *  beside them. `children` is the way in (the button); `signIn` closes the column.
 *  `partOf` is Todo GTD's address, on the apps that live inside it. */
function FrontDoor({
  title,
  lead,
  points,
  footnote,
  demo,
  signIn,
  children,
  partOf,
  eyebrow = 'Free \u00b7 one click \u00b7 nothing to install',
}: {
  title: string;
  lead: ReactNode;
  points: string[][];
  footnote: ReactNode;
  demo: ReactNode;
  signIn: ReactNode;
  children: ReactNode;
  partOf?: string;
  eyebrow?: string;
}) {
  return (
    <PageFrame wide>
      <div className="grid gap-x-16 gap-y-10 rounded-3xl bg-band bg-[radial-gradient(520px_circle_at_100%_0,var(--color-band-glow),transparent)] px-5 py-10 text-band-text lg:grid-cols-[minmax(0,1fr)_400px] lg:rounded-[32px] lg:px-14 lg:py-16">
        <div className="min-w-0">
          {partOf && (
            <a
              href={partOf}
              className="mb-4 inline-flex items-center gap-2 rounded-full bg-white/10 py-1 pl-1.5 pr-3 text-sm font-semibold text-white hover:bg-white/20"
            >
              <Logo app="todo" className="h-5 w-5" />
              Part of Todo GTD
            </a>
          )}
          <p className="text-[13px] font-bold uppercase tracking-widest text-band-accent">{eyebrow}</p>
          <h1 className="mt-2 text-balance font-heading text-4xl font-bold tracking-tight text-white lg:text-5xl">
            {title}
          </h1>
          <p className="mt-4 max-w-xl text-lg">{lead}</p>
          {children}
          <ul className="mt-8">
            {points.map(([head, text]) => (
              <li key={head} className="border-t border-white/15 py-3.5">
                <b className="block font-heading text-[17px] text-white">{head}</b>
                {text}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[13px]">{footnote}</p>
          {signIn}
        </div>
        {demo}
      </div>
    </PageFrame>
  );
}
