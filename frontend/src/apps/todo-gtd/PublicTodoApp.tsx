// Todo GTD — the list's web app, served at /app.
//
// This component is the WHOLE tree on /app: Root.tsx renders it and nothing
// around it. Its BrowserRouter has the fixed basename /app, so deep links and
// reloads under /app/... resolve to the right page. Which list it shows is the
// session's (session.ts): SessionGate asks first, and nothing else loads until
// the answer has pinned the list every later request names.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { APP } from '../../core/app';
import { AppOff } from './AppOff';
import { AreasPage } from './AreasPage';
import { PageFrame } from './components/PageFrame';
import { ConnectPage } from './ConnectPage';
import { DonePage } from './DonePage';
import { InboxPage } from './InboxPage';
import { NextActionsPage } from './NextActionsPage';
import { ProjectDetailPage } from './ProjectDetailPage';
import { ProjectsPage } from './ProjectsPage';
import { readHop, settleHop, suiteConfig, type Settled } from './hop';
import { TODO_PUBLIC_BASE } from './publicMode';
import { PutAwayPage } from './PutAwayPage';
import { ReviewPage } from './ReviewPage';
import { SearchPage } from './SearchPage';
import { bootstrap, useSession } from './session';
import { SomedayPage } from './SomedayPage';
import { TodayPage } from './TodayPage';
import { WaitingPage } from './WaitingPage';

/** Nothing until the session has named the list, so no request ever goes out
 * without X-List. Signed out, the page is already on its way home; a list that
 * changed under this tab is already reloading. A put-away list, at boot or on a
 * later 403, shows only PutAwayPage, and an app the account has turned off shows
 * only AppOff. A page reached through the app bar settles its hop first (hop.ts):
 * nothing shows while it is on its way to another address. */
export function SessionGate({ children }: { children: ReactNode }) {
  const { kind, session } = useSession();
  const [hop] = useState(readHop);
  const [hopped, setHopped] = useState<Settled | 'settling'>(hop ? 'settling' : 'stay');
  useEffect(() => {
    void bootstrap();
    suiteConfig().catch(() => {});
  }, []);
  const listId = session?.list_id ?? null;
  // Once per page load: a second #to= would mint a second link. A put-away list
  // settles too: another account's put-away page is not where a hop should end.
  const named = kind === 'ok' || kind === 'putAway';
  const settled = useRef(false);
  useEffect(() => {
    if (!named || !hop || settled.current) return;
    settled.current = true;
    void settleHop(hop, listId).then(setHopped);
  }, [named, hop, listId]);
  if (named && hopped === 'stuck') {
    return (
      <PageFrame>
        <p role="alert" className="text-charcoal">
          Could not finish opening this app: this browser is signed in to another account here. Check your connection
          and try again.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-4 rounded-lg bg-brand-dark px-5 py-2.5 font-heading text-white hover:bg-brand-deep"
        >
          Try again
        </button>
      </PageFrame>
    );
  }
  if (named && hopped !== 'stay') return null;
  if (kind === 'ok') return session && !session.apps.includes(APP) ? <AppOff /> : children;
  if (kind === 'putAway') return <PutAwayPage />;
  if (kind === 'error') {
    return (
      <PageFrame>
        <p role="alert" className="text-charcoal">
          Could not reach the server. Check your connection and reload the page.
        </p>
      </PageFrame>
    );
  }
  return null;
}

/** The todo app. Routes are relative to the /app basename: Today at the root,
 * the rest as bare slugs. */
export function PublicTodoApp() {
  useEffect(() => {
    document.title = 'Todos';
  }, []);

  return (
    <SessionGate>
      <BrowserRouter basename={TODO_PUBLIC_BASE ?? undefined}>
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/next" element={<NextActionsPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/areas" element={<AreasPage />} />
          <Route path="/waiting" element={<WaitingPage />} />
          <Route path="/someday" element={<SomedayPage />} />
          <Route path="/done" element={<DonePage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/connect" element={<ConnectPage />} />
          {/* Anything else stays inside the list. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </SessionGate>
  );
}
