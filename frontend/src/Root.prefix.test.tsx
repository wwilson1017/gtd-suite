// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('./apps/notes-gtd/NotesApp', () => ({ NotesApp: () => <div>Notes app</div> }));
vi.mock('./apps/todo-gtd/SignInPage', () => ({
  SignInPage: ({ token }: { token: string }) => <div>Sign in {token}</div>,
}));
vi.mock('./apps/todo-gtd/CapturePage', () => ({
  CapturePage: ({ token }: { token: string }) => <div>Capture {token}</div>,
}));
vi.mock('./apps/todo-gtd/LandingPage', () => ({ LandingPage: () => <div>Landing</div> }));
vi.mock('./apps/sites/SitesConnectFlow', () => ({ SitesConnectFlow: () => <div>Connect</div> }));

afterEach(() => {
  document.head.innerHTML = '';
  vi.resetModules();
});

it.each([
  ['notes', '/notes/app', 'Notes app'],
  ['notes', '/notes/signin/TOKEN', 'Sign in TOKEN'],
  ['notes', '/notes/c/TOKEN', 'Capture TOKEN'],
  ['notes', '/notes', 'Landing'],
  ['notes', '/notes/', 'Landing'],
  ['sites', '/sites/connect', 'Connect'],
])('boots %s at %s', async (key, path, expected) => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  document.head.innerHTML = `<meta name="gtd-app" content="${key}"><meta name="gtd-base" content="/${key}">`;
  window.history.replaceState(null, '', path);
  vi.resetModules();
  const { default: Root } = await import('./Root');
  const host = document.createElement('div');
  const root = createRoot(host);
  try {
    await act(async () => {
      root.render(<Root />);
    });
    expect(host.textContent).toBe(expected);
  } finally {
    await act(async () => root.unmount());
  }
});
