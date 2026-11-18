import { lazy, Suspense } from 'react';
import { isTodoPublicMode } from './apps/todo-gtd/publicMode';
import { BASE, APP } from './core/app';

const PublicTodoApp = lazy(() => import('./apps/todo-gtd/PublicTodoApp').then((m) => ({ default: m.PublicTodoApp })));
const CapturePage = lazy(() => import('./apps/todo-gtd/CapturePage').then((m) => ({ default: m.CapturePage })));
const SignInPage = lazy(() => import('./apps/todo-gtd/SignInPage').then((m) => ({ default: m.SignInPage })));
const ProjectsApp = lazy(() => import('./apps/projects-gtd/ProjectsApp').then((m) => ({ default: m.ProjectsApp })));
const SitesConnectFlow = lazy(() =>
  import('./apps/sites/SitesConnectFlow').then((m) => ({ default: m.SitesConnectFlow })),
);
const SitesApp = lazy(() => import('./apps/sites/SitesApp').then((m) => ({ default: m.SitesApp })));
const NotesApp = lazy(() => import('./apps/notes-gtd/NotesApp').then((m) => ({ default: m.NotesApp })));
const BrainApp = lazy(() => import('./apps/brain/BrainApp').then((m) => ({ default: m.BrainApp })));
const HopBack = lazy(() => import('./apps/todo-gtd/components/AppBar').then((m) => ({ default: m.HopBack })));
const LandingPage = lazy(() => import('./apps/todo-gtd/LandingPage').then((m) => ({ default: m.LandingPage })));

/** `/c/{token}` or `/signin/{token}` → the token, else null. */
function tokenAfter(prefix: string, path: string): string | null {
  const parts = path.split('/').filter(Boolean);
  return parts[0] === prefix && parts[1] ? parts[1] : null;
}

function pick() {
  // The web app owns its own router (and basename); nothing may wrap it in another.
  // On another app's address (core/app.ts) /app is that app; the rest is shared.
  if (isTodoPublicMode) {
    if (APP === 'projects') return <ProjectsApp />;
    if (APP === 'sites') return <SitesApp />;
    if (APP === 'brain') return <BrainApp />;
    return APP === 'notes' ? <NotesApp /> : <PublicTodoApp />;
  }
  const path = window.location.pathname.slice(BASE.length);
  if (APP === 'sites' && path === '/connect') return <SitesConnectFlow />;
  const signin = tokenAfter('signin', path);
  if (signin) return <SignInPage token={signin} />;
  const capture = tokenAfter('c', path);
  if (capture) return <CapturePage token={capture} />;
  // Signed out at the end of an app bar hop: back for a sign-in link (hop.ts).
  if (window.location.hash.startsWith('#from='))
    return (
      <HopBack>
        <LandingPage />
      </HopBack>
    );
  return <LandingPage />;
}

/**
 * The composition root — what `main.tsx` renders, and the whole of the boot decision:
 * which of the four surfaces this address is. Each is lazy, so a capture bookmark
 * never downloads the todo app.
 *
 * Kept as a component (rather than inlined into `main.tsx`) so it stays testable:
 * `main.tsx` calls `createRoot` at module scope and renders on import.
 */
export default function Root() {
  return <Suspense fallback={null}>{pick()}</Suspense>;
}
