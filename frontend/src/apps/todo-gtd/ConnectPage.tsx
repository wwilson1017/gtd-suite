import { BASE } from '../../core/app';
// The suite's account cards, shown in Settings (settings/SettingsPage.tsx) and on Common
// Brain's Connect page: the email, the account number, signing in on another device and
// signing this one out, the agent link's card (Common Brain's), and Todo GTD's own (the
// list's name and time zone, the inbox triage layout).
import { useId, useMemo, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { apiErrorMessage } from '../../core/api/client';
import { useTriageLayout, type TriageLayout } from './triageLayout';
import {
  createSignInLink,
  getAgentLink,
  regenerateAgentLink,
  setEmail,
  setName,
  setTz,
  signOut,
  signOutEverywhere,
} from './api';
import { pastePrompt, reachOf } from './clients';
import { ClientSteps } from './components/ClientSteps';
import { ConnectAnimation } from './components/ConnectAnimation';
import { CopyButton } from './components/CopyButton';
import { LinkCard } from './components/LinkCard';
import { updateSession, useSession } from './session';
import type { EmailStatus, SignInLink } from './types';
import { useTodoMeta } from './useTodoMeta';

const inputCls =
  'min-w-0 flex-1 rounded-lg border border-line bg-cream px-3 py-2 text-base sm:text-sm text-charcoal focus:border-brand focus:outline-none';
const cardCls = 'rounded-xl border border-line-faint bg-cream p-4 sm:p-5';
/** A status line: green for done, amber while waiting on the person. */
const okCls =
  'flex items-center gap-2.5 rounded-xl bg-green-50 px-4 py-3 font-heading text-sm font-semibold text-green-800 dark:bg-green-950/50 dark:text-green-300';
const waitCls =
  'flex items-center gap-2.5 rounded-xl bg-amber-50 px-4 py-3 font-heading text-sm font-semibold text-amber-800 dark:bg-amber-950/40 dark:text-amber-300';
const h2Cls = 'font-heading text-sm font-bold text-charcoal';
const btnCls =
  'shrink-0 rounded-lg border border-line bg-cream px-3 py-2 text-sm font-heading text-charcoal hover:bg-sand disabled:opacity-40';
const primaryCls =
  'shrink-0 rounded-lg bg-brand-dark px-4 py-2 text-sm font-heading font-semibold text-white hover:bg-brand-deep disabled:opacity-40';
/** A copyable text snippet (the paste message, the brain tickle), beside its CopyButton. */
const snippetCls =
  'min-w-0 flex-1 select-all whitespace-pre-wrap break-words rounded-lg border border-line bg-sand px-3 py-2 font-sans text-xs text-charcoal';

type Saved = { kind: 'idle' | 'saving' | 'saved' } | { kind: 'error'; text: string };

function SaveNote({ state }: { state: Saved }) {
  return (
    <p role="status" className="mt-1 text-xs text-muted">
      {state.kind === 'saved' && 'Saved.'}
      {state.kind === 'error' && <span className="text-brand-ink">{state.text}</span>}
    </p>
  );
}

export function ListName() {
  const id = useId();
  const { filters, refreshMeta } = useTodoMeta();
  const [name, setNameText] = useState<string | null>(null); // null = not edited yet
  const [state, setState] = useState<Saved>({ kind: 'idle' });

  const save = async () => {
    setState({ kind: 'saving' });
    try {
      // Untouched, the field shows the stored name: saving must not clear it.
      setNameText(await setName((name ?? filters?.name ?? '').trim()));
      await refreshMeta(); // the header and the tab title follow
      setState({ kind: 'saved' });
    } catch (e) {
      setState({ kind: 'error', text: apiErrorMessage(e, 'Could not save the name.') });
    }
  };

  return (
    <section className={cardCls}>
      <h2 className={h2Cls}>
        <label htmlFor={id}>List name</label>
      </h2>
      <p className="mt-1 text-xs text-muted">
        Optional. Shown at the top of the app, in the browser tab and on a home-screen icon added after you set it.
        Leave it empty to remove it.
      </p>
      <form
        className="mt-2 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <input
          id={id}
          value={name ?? filters?.name ?? ''}
          maxLength={80}
          autoComplete="off"
          onChange={(e) => {
            setNameText(e.target.value);
            setState({ kind: 'idle' });
          }}
          placeholder="Home, Work, …"
          className={inputCls}
        />
        <button type="submit" disabled={state.kind === 'saving'} className={btnCls}>
          Save
        </button>
      </form>
      <SaveNote state={state} />
    </section>
  );
}

const count = (n: number) => n.toLocaleString('en');

/** What saving (or "Send again") adds to the card, from the server's answer. A first
 *  link sent needs no word: the card itself now says to check the inbox. */
function emailNote(r: EmailStatus, again: boolean): string {
  if (r.sent) return again ? 'Sent.' : '';
  if (r.email && !r.verified) {
    return again ? 'Wait a few minutes before sending again.' : 'Saved. Wait a few minutes, then press Send again.';
  }
  return 'Saved.';
}

/** The account's email, in three states: none yet (what it gives, and the field), waiting
 *  for its link to be opened (send again, or use another), and confirmed. Saving one mails
 *  it a link; opening the link confirms it, which keeps the account, lets it be signed in
 *  to from any device and, on a hosted server, raises its limits. Rendered only when the
 *  server can send mail. */
export function EmailSection() {
  const id = useId();
  const session = useSession().session;
  const onFile = session?.email ?? null;
  const verified = session?.verified === true;
  const hosted = session?.hosted === true;
  const caps = session?.caps;
  const [email, setEmailText] = useState<string | null>(null); // null = not edited yet
  const [changing, setChanging] = useState(false); // "Use a different email", while one waits
  const [state, setState] = useState<Saved>({ kind: 'idle' });
  const [note, setNote] = useState('');

  const save = async (value: string, again = false) => {
    setState({ kind: 'saving' });
    setNote('');
    try {
      // An empty field clears the address (and any link already mailed to it).
      const result = await setEmail(value);
      updateSession({ email: result.email, verified: result.verified, caps: result.caps });
      setEmailText(null);
      setChanging(false);
      setNote(emailNote(result, again));
      setState({ kind: 'idle' });
    } catch (e) {
      setState({ kind: 'error', text: apiErrorMessage(e, 'Could not save the email.') });
    }
  };
  const busy = state.kind === 'saving';

  const limits = hosted && caps && (
    <p className="mt-3 text-xs text-muted">
      {verified ? 'It holds' : 'Until then it holds'} up to {count(caps.todos)} todos, {count(caps.projects)} projects
      and {count(caps.areas)} areas.
    </p>
  );
  const form = (label: string, primary: boolean, shown: string) => (
    <form
      className="mt-3 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void save((email ?? shown).trim());
      }}
    >
      <input
        id={id}
        type="email"
        autoComplete="email"
        aria-label="Your email"
        value={email ?? shown}
        onChange={(e) => {
          setEmailText(e.target.value);
          setState({ kind: 'idle' });
          setNote('');
        }}
        placeholder="you@example.com"
        className={`${inputCls} basis-56 py-2.5`}
      />
      <button type="submit" disabled={busy} className={primary ? primaryCls : `${btnCls} px-4`}>
        {label}
      </button>
    </form>
  );
  const status = (
    <p role="status" className="mt-2 text-xs text-muted empty:hidden">
      {note}
      {state.kind === 'error' && <span className="text-brand-ink">{state.text}</span>}
    </p>
  );

  if (verified && !changing) {
    return (
      <section className={cardCls}>
        <p className={`${okCls} break-all`}>
          <span aria-hidden="true" className="h-2.5 w-2.5 flex-none rounded-full bg-current" />
          {onFile} · confirmed
        </p>
        <p className="mt-3 text-sm text-muted">
          {hosted ? 'Your account is kept for good. ' : ''}Sign in with this email from the home page on any device.
        </p>
        {form('Change', false, onFile ?? '')}
        <p className="mt-1 text-xs text-muted">Save it empty to remove the email.</p>
        {status}
        {limits}
      </section>
    );
  }
  if (onFile !== null && !changing) {
    return (
      <section className={cardCls}>
        <p className={`${waitCls} break-all`}>
          <span aria-hidden="true" className="h-2.5 w-2.5 flex-none animate-pulse rounded-full bg-current" />
          Check your inbox: we sent a link to {onFile}
        </p>
        <p className="mt-3 text-sm text-muted">
          Open the link and this step is done. If this email already has an account, the link takes you back to it.
          Nothing there? Look in spam, or send it again.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => void save(onFile, true)} disabled={busy} className={primaryCls}>
            Send again
          </button>
          <button type="button" onClick={() => setChanging(true)} disabled={busy} className={`${btnCls} px-4`}>
            Use a different email
          </button>
        </div>
        {status}
        {limits}
      </section>
    );
  }
  return (
    <section className={cardCls}>
      <h3 className="font-heading text-base font-bold text-charcoal">
        {changing ? 'Use a different email' : 'Right now your account lives only in this browser.'}
      </h3>
      {!changing && (
        <>
          <p className="mt-1 text-sm text-muted">Add your email and you get:</p>
          <ul className="mt-3 space-y-1.5 text-sm text-charcoal">
            {(hosted
              ? [
                  'Everything kept for good: lists, notes, projects, pages',
                  'Sign in on your phone, laptop, anywhere',
                  'Higher limits, free',
                ]
              : ['Sign in on your phone, laptop, anywhere', 'A way back in if this browser signs out']
            ).map((perk) => (
              <li key={perk} className="flex gap-2">
                <span aria-hidden="true" className="font-extrabold text-green-700 dark:text-green-400">
                  ✓
                </span>
                {perk}
              </li>
            ))}
          </ul>
        </>
      )}
      {form('Send link', true, '')}
      <p className="mt-2 text-xs text-muted">We email one link. Open it and you&rsquo;re done. No password, ever.</p>
      {changing && (
        <button
          type="button"
          onClick={() => setChanging(false)}
          className="mt-2 text-sm text-muted hover:text-charcoal"
        >
          Cancel
        </button>
      )}
      {status}
      {limits}
    </section>
  );
}

/** The account's number, on every server: unlike the email, it needs no mail. */
export function AccountNumber() {
  const number = useSession().session?.account_no;
  if (!number) return null;
  return (
    <section className={cardCls}>
      <h2 className={h2Cls}>Account number</h2>
      <p className="mt-1 select-all text-sm text-charcoal">{number}</p>
    </section>
  );
}

export function TimeZone() {
  const id = useId();
  const { filters, refreshMeta } = useTodoMeta();
  const [state, setState] = useState<Saved>({ kind: 'idle' });
  const current = filters?.tz ?? '';
  // The list's own zone always gets an option, even where the browser's list lacks it.
  const zones = useMemo(() => {
    const all = Intl.supportedValuesOf('timeZone');
    return current && !all.includes(current) ? [current, ...all] : all;
  }, [current]);

  const change = async (tz: string) => {
    setState({ kind: 'saving' });
    try {
      await setTz(tz);
      await refreshMeta(); // "today" everywhere follows the new zone
      setState({ kind: 'saved' });
    } catch (e) {
      setState({ kind: 'error', text: apiErrorMessage(e, 'Could not change the time zone.') });
    }
  };

  return (
    <section className={cardCls}>
      <h2 className={h2Cls}>
        <label htmlFor={id}>Time zone</label>
      </h2>
      <p className="mt-1 text-xs text-muted">
        Decides what counts as &ldquo;today&rdquo; for due dates and repeats — here and for your AI tools.
      </p>
      <select
        id={id}
        value={current}
        disabled={!current || state.kind === 'saving'}
        onChange={(e) => void change(e.target.value)}
        className={`${inputCls} mt-2 w-full`}
      >
        {!current && <option value="">Loading…</option>}
        {zones.map((z) => (
          <option key={z} value={z}>
            {z}
          </option>
        ))}
      </select>
      <SaveNote state={state} />
    </section>
  );
}

/** The agent link, always on show, with the per-tool setup filled in with it (Common
 *  Brain's Connect page; the other apps show Settings › Connect your AI). A signed-in
 *  browser can read and change everything, so showing the agent link here gives away
 *  nothing it did not already have. */
export function AgentLink() {
  const [url, setUrl] = useState('');
  const reaches = reachOf(useSession().session?.apps ?? []);
  return (
    <LinkCard
      title="Connect your AI to GTD"
      accent="border-line-faint bg-cream"
      blurb={
        <>
          One link for all your GTD apps. Your AI tools use it to <strong>read, add and update</strong> your{' '}
          {reaches || 'apps'}. It cannot delete anything, and it cannot see or change the links on this page. Treat it
          like a key: anyone holding it can do the same. Open it in a browser to see what it offers.
        </>
      }
      load={getAgentLink}
      regenerate={regenerateAgentLink}
      regenerateConfirm={
        'Make a new agent link?\n\nThe old link stops working immediately, and every AI ' +
        'tool you connected with it must be re-added with the new one. Your capture link is ' +
        'not affected, and every signed-in device stays signed in.'
      }
      copyLabel="Copy the agent link"
      onUrl={setUrl}
    >
      <ConnectAnimation />
      <h3 className="mt-4 text-sm font-semibold text-charcoal">
        Paste into an AI agent{' '}
        <span className="rounded border border-line px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">
          Experimental
        </span>
      </h3>
      <p className="mb-2 mt-1 text-xs text-muted">
        Works fully in Grok: paste it into a chat and Grok can read, add and update. ChatGPT can only read the list this
        way. Agents that fetch web addresses or run commands, such as Claude Code or Codex, may need only this message
        too. Where it falls short, connect the link below instead.
      </p>
      <div className="flex items-start gap-2">
        <pre className={snippetCls}>{pastePrompt(url)}</pre>
        <CopyButton text={() => pastePrompt(url)} label="Copy the message for an AI agent" />
      </div>
      <h3 className="mt-4 text-sm font-semibold text-charcoal">Add it to your AI tool</h3>
      <p className="mb-2 mt-1 text-xs text-muted">
        A chat app&rsquo;s browsing can at most read from a pasted link, and ChatGPT will not open one that holds a key:
        add the link once in the app&rsquo;s connector settings to write too. Coding tools take it as an MCP server.
        Pick yours; your agent link is filled in.
      </p>
      <ClientSteps url={url} />
    </LinkCard>
  );
}

/** Connect → Sign in on another device: a one-hour, single-use link, shown as a
 *  QR code for a phone's camera and as text to copy. */
export function SignInElsewhere() {
  const [link, setLink] = useState<SignInLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const make = async () => {
    setBusy(true);
    setError('');
    try {
      setLink(await createSignInLink());
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not make a sign-in link — try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={cardCls}>
      <h2 className={h2Cls}>Sign in on another device</h2>
      <p className="mt-1 text-xs text-muted">
        Scan the code with the other device&rsquo;s camera, or open the link there. It works once, for an hour, and{' '}
        <strong>anyone who scans it gets into this list</strong> &mdash; so show it only to your own devices.
      </p>
      {link && (
        <>
          <div className="mt-3 flex justify-center rounded-xl bg-white p-3">
            <QRCodeSVG value={link.url} size={176} title="Sign-in code" />
          </div>
          <div className="mt-3 flex items-center gap-2">
            <input
              readOnly
              value={link.url}
              aria-label="Sign-in link"
              onFocus={(e) => e.currentTarget.select()}
              onClick={(e) => e.currentTarget.select()}
              className="min-w-0 flex-1 rounded-lg border border-line bg-sand px-3 py-2 text-xs text-charcoal"
            />
            <CopyButton text={() => link.url} label="Copy the sign-in link" />
          </div>
        </>
      )}
      <button type="button" onClick={() => void make()} disabled={busy} className={`${btnCls} mt-3`}>
        {busy ? 'Working…' : link ? 'Make a new code' : 'Show a sign-in code'}
      </button>
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </section>
  );
}

/** Connect → This device: sign out here, or everywhere. The warning is blunt
 *  when the list has no confirmed email: sign-in mail goes only to a confirmed
 *  address, so then a signed-in device is the only way back. */
export function ThisDevice() {
  const session = useSession().session;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const noWayBack = !(session?.verified && session.mail);

  const run = async (everywhere: boolean) => {
    const warning = everywhere
      ? noWayBack
        ? 'Sign out everywhere?\n\nThis list has no confirmed email, so there is no way back ' +
          'into it after signing out everywhere.'
        : 'Sign out everywhere?\n\nEvery device signed in to this list is signed out, this one ' +
          'too, and unused sign-in links stop working. Sign back in with your email.'
      : noWayBack
        ? 'Sign out of this list on this device?\n\nThis list has no confirmed email, so there ' +
          'is no way back into it after signing out — unless another device that is still ' +
          'signed in makes you a sign-in code.'
        : 'Sign out of this list on this device?\n\nSign back in with your email.';
    if (!window.confirm(warning)) return;
    setBusy(true);
    setError('');
    try {
      await (everywhere ? signOutEverywhere() : signOut());
      window.location.replace(BASE + '/');
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not sign out — try again.'));
      setBusy(false);
    }
  };

  return (
    <section className={cardCls}>
      <h2 className={h2Cls}>This device</h2>
      <p className="mt-1 text-xs text-muted">
        This browser stays signed in to this list until you sign out. Sign out everywhere if a device was lost or
        someone else had a sign-in code. Your agent and capture links are separate and keep working.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" onClick={() => void run(false)} disabled={busy} className={btnCls}>
          Sign out
        </button>
        <button type="button" onClick={() => void run(true)} disabled={busy} className={`${btnCls} text-brand-ink`}>
          Sign out everywhere
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </section>
  );
}

/** Compact / Expanded, a native select like the menu layout's. */
export function TriageLayoutToggle() {
  const [layout, setLayout] = useTriageLayout();
  return (
    <select
      aria-label="Inbox triage layout"
      value={layout}
      onChange={(e) => setLayout(e.target.value as TriageLayout)}
      className="rounded-lg border border-line bg-cream px-2 py-1.5 text-sm text-charcoal focus:border-brand focus:outline-none"
    >
      <option value="compact">Compact</option>
      <option value="expanded">Expanded</option>
    </select>
  );
}
