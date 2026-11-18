// @vitest-environment jsdom
//
// "Next actions, from Todo" on a Projects GTD project that is the home of a Todo
// project: it asks Todo for that project's open next actions (the server leaves out
// finished, waiting and deferred ones for exactly this request), lists them, and
// links back to the Todo project. Nothing for a project with no Todo project, a
// dropped one, or with Todo off; on the app's old address the list stays and the
// link goes.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session, Todo } from '../todo-gtd/types';
import type { Project } from './types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(),
  listTodos: vi.fn(),
  todoFetch: vi.fn(),
}));
vi.mock('../todo-gtd/api', () => api);

const HERE = window.location.origin;
const SESSION: Session = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['todo', 'notes', 'projects'],
};
const SUITE = {
  app: 'projects',
  apps: {
    todo: { title: 'Todo GTD', url: HERE },
    projects: { title: 'Projects GTD', url: `${HERE}/projects` },
  },
};
const TODOS = [
  { id: 1, title: 'Cost the pumpkin swirl', context: '@computer' },
  { id: 2, title: 'Book the tasting for the team', context: '' },
] as Todo[];

function project(todo?: Project['todo_project']): Project {
  return { id: 31, name: 'Plan the fall menu', todo_project: todo } as Project;
}
const LINKED = { id: 5, name: 'Plan the fall menu', status: 'active' } as const;

let container: HTMLDivElement;
let root: Root;
let meta: HTMLMetaElement;

/** The panel from a fresh module graph: hop.ts asks for the config once per page load. */
async function show(shown: Project, { apps = SESSION.apps, suite = SUITE as object } = {}) {
  vi.resetModules();
  api.getConfig.mockResolvedValue(suite);
  api.getSession.mockResolvedValue({ ...SESSION, apps });
  const { TodoNextActions } = await import('./ProjectPage');
  const session = await import('../todo-gtd/session');
  await act(async () => {
    await session.bootstrap();
  });
  await act(async () => {
    root.render(<TodoNextActions project={shown} />);
  });
}

const panel = () => container.querySelector('section[aria-label="Next actions, from Todo"]');

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  api.listTodos.mockResolvedValue(TODOS);
  // This page is Projects GTD's (core/app.ts reads the server's meta).
  meta = document.createElement('meta');
  meta.name = 'gtd-app';
  meta.content = 'projects';
  document.head.appendChild(meta);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  meta.remove();
});

describe('Next actions, from Todo', () => {
  it("lists the Todo project's open next actions and links back to it", async () => {
    await show(project(LINKED));
    // Exactly this request: next actions only, and no include_deferred.
    expect(api.listTodos).toHaveBeenCalledExactlyOnceWith({ project: '5', status: 'next_action' });
    expect(panel()!.querySelector('h2')!.textContent).toBe('Next actions');
    expect(panel()!.textContent).toContain('from Todo');
    expect([...panel()!.querySelectorAll('li')].map((li) => li.textContent)).toEqual([
      'Cost the pumpkin swirl@computer',
      'Book the tasting for the team',
    ]);
    const back = panel()!.querySelector('a')!;
    expect(back.textContent).toBe('Open in Todo →');
    expect(back.getAttribute('href')).toBe(`${HERE}/app/projects/5`);
    // They are listed, not worked, here: nothing to tick.
    expect(panel()!.querySelectorAll('input, button')).toHaveLength(0);
  });

  it('says so when there are none, and still links back', async () => {
    api.listTodos.mockResolvedValue([]);
    await show(project(LINKED));
    expect(panel()!.textContent).toContain('No next actions in Todo right now.');
    expect(panel()!.querySelector('a')!.getAttribute('href')).toBe(`${HERE}/app/projects/5`);
  });

  it('is absent on a project that is no Todo project’s home, and asks for nothing', async () => {
    await show(project());
    expect(panel()).toBeNull();
    expect(api.listTodos).not.toHaveBeenCalled();
  });

  it('is absent for a dropped Todo project', async () => {
    await show(project({ ...LINKED, status: 'dropped' }));
    expect(panel()).toBeNull();
    expect(api.listTodos).not.toHaveBeenCalled();
  });

  it('is absent with Todo off for the account', async () => {
    await show(project(LINKED), { apps: ['projects'] });
    expect(panel()).toBeNull();
    expect(api.listTodos).not.toHaveBeenCalled();
  });

  it("keeps the list and leaves the link out on the app's old address", async () => {
    await show(project(LINKED), { suite: { ...SUITE, moved: `${HERE}/projects` } });
    expect(panel()!.querySelectorAll('li')).toHaveLength(2);
    expect(panel()!.querySelector('a')).toBeNull();
  });

  it('where Todo has its own host, links to Todo through the hop', async () => {
    await show(project(LINKED), {
      suite: { ...SUITE, apps: { ...SUITE.apps, todo: { title: 'Todo GTD', url: 'https://todo.example' } } },
    });
    expect(panel()!.querySelector('a')!.getAttribute('href')).toBe('https://todo.example/app#from=projects.7');
  });
});
