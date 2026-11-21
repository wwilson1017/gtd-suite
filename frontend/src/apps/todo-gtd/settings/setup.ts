// Getting set up, in every app: connect an AI, then (where the server can mail) add an
// email. One hook says how far the account is (useSetup), and Settings' two-step box,
// its menu badges and the header's next-step button all read it. Once every step is
// done, the box and the button are gone for good (HeaderSetup.tsx has the button).
import { useEffect, type ReactNode } from 'react';
import { getSession } from '../api';
import { listChanged, pinnedListId, refreshAiTools, updateSession, useSession } from '../session';
import type { Session } from '../types';

export type StepKey = 'ai' | 'email';
/** 'pending': an email is saved but its link has not been opened yet. */
export type StepState = 'todo' | 'pending' | 'done';
export interface Step {
  key: StepKey;
  state: StepState;
}
export interface Setup {
  steps: Step[];
  /** The first step not done, or null once all are. */
  next: Step | null;
}

/** Step 1 is done once an AI tool has called (session.ai_tools); step 2, there only when
 *  the server can mail, once the email is confirmed. Nothing to show while loading. */
export function setupOf(session: Session | null): Setup {
  if (!session) return { steps: [], next: null };
  const steps: Step[] = [{ key: 'ai', state: session.ai_tools?.length ? 'done' : 'todo' }];
  if (session.mail) {
    steps.push({ key: 'email', state: session.verified ? 'done' : session.email ? 'pending' : 'todo' });
  }
  return { steps, next: steps.find((s) => s.state !== 'done') ?? null };
}

export function useSetup(): Setup {
  return setupOf(useSession().session);
}

/** While a step is open, ask again each time the window comes back into focus: the person
 *  has been away adding the link to their AI, or opening the emailed link in another tab. */
export function useSetupOnFocus() {
  const { steps } = useSetup();
  // Each on its own: an email can be confirmed while the AI step is still open.
  const ai = steps.some((s) => s.key === 'ai' && s.state !== 'done');
  const email = steps.some((s) => s.key === 'email' && s.state === 'pending');
  useEffect(() => {
    if (!ai && !email) return;
    const refresh = () => {
      if (ai) void refreshAiTools();
      if (email) void refreshEmail();
    };
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  }, [ai, email]);
}

/** The email's state, asked again. Opening a link mailed to an address that already had an
 *  account signs the browser in there: then this tab is on another list, so it starts over. */
function refreshEmail(): Promise<void> {
  const listId = pinnedListId();
  return getSession().then(
    (s) =>
      s.list_id !== listId ? listChanged() : updateSession({ email: s.email, verified: s.verified, caps: s.caps }),
    () => {},
  );
}

/** One section of Settings: its address (/connect/<key>), its menu line and its page. */
export interface Section {
  key: string;
  /** A glyph for the menu. */
  icon: string;
  title: string;
  sub: string;
  body: ReactNode;
}

export const SETTINGS = '/connect';

/** Where a sign-up opens: a brand-new account lands once on Connect your AI. Common Brain
 *  keeps its own Connect page and first-run set-up until it moves to Settings, so it opens Home. */
export function firstPage(app: string, welcome: boolean): string {
  return welcome && app !== 'brain' ? '/app' + SETTINGS + '/ai?welcome' : '/app';
}
export const LABEL: Record<StepKey, string> = { ai: 'Connect your AI', email: 'Add your email' };
