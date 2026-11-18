// @vitest-environment jsdom
//
// A Todo project's home in Projects GTD, on Todo's two pages. The project's own page
// offers the step up ("Outgrowing a list?") while Projects GTD is on and there is no
// link, and shows a bar that opens the Projects GTD project once there is one; the
// Projects list marks a linked project with a "Board" chip. A link to an archived
// Projects GTD project, or from a dropped Todo project, shows nothing. Nothing here is
// labelled as new.
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../core/api/client';
import type { ProjectLink, Session, TodoProject } from './types';

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  getConfig: vi.fn(),
  getFilters: vi.fn(),
  listProjects: vi.fn(),
  listTodos: vi.fn(),
  listProjectLinks: vi.fn(),
  createProjectLink: vi.fn(),
  updateProject: vi.fn(),
}));
vi.mock('./api', () => api);

import { ProjectDetailPage } from './ProjectDetailPage';
import { ProjectsPage } from './ProjectsPage';
import { bootstrap, resetSession } from './session';

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

function project(over: Partial<TodoProject> = {}): TodoProject {
  return {
    id: 5,
    name: 'Plan the fall menu',
    notes: '',
    status: 'active',
    open_count: 3,
    created_at: '2026-11-01T12:00:00Z',
    updated_at: '2026-11-01T12:00:00Z',
    ...over,
  };
}

function link(over: Partial<ProjectLink> = {}): ProjectLink {
  return {
    project_id: 5,
    project_name: 'Plan the fall menu',
    project_status: 'active',
    board_id: 31,
    board_name: 'Plan the fall menu',
    board_status: 'active',
    created_at: '2026-11-02T12:00:00Z',
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

async function signIn(apps = SESSION.apps) {
  resetSession();
  api.getSession.mockResolvedValue({ ...SESSION, apps });
  await act(async () => {
    await bootstrap();
  });
}

async function show(path: string) {
  await act(async () => {
    root.render(
      <MemoryRouter key={path} initialEntries={[path]}>
        <Routes>
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });
}

const card = () =>
  [...container.querySelectorAll('section')].find((s) => s.textContent?.includes('Outgrowing a list?')) ?? null;
const button = () => card()?.querySelector('button') ?? null;
const bar = () => [...container.querySelectorAll('p')].find((p) => p.textContent?.includes('are in Projects GTD'));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  // One address for the whole file (hop.ts asks once per page load): the link is to the page itself.
  api.getConfig.mockResolvedValue({
    app: 'todo',
    apps: {
      todo: { title: 'Todo GTD', url: HERE },
      projects: { title: 'Projects GTD', url: `${HERE}/projects` },
    },
  });
  api.getFilters.mockResolvedValue({ contexts: [], tags: [], status_counts: {} });
  api.listProjects.mockResolvedValue([project()]);
  api.listTodos.mockResolvedValue([]);
  api.listProjectLinks.mockResolvedValue([]);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("a Todo project's page", () => {
  it('offers the step up, and shows the way to its home once the button is pressed', async () => {
    await signIn();
    api.createProjectLink.mockResolvedValue(link());
    await show('/projects/5');

    // The whole card: no badge, nothing marked as new.
    expect(card()?.textContent).toBe(
      'Outgrowing a list?' +
        'Give this project a board, files and messages. Your to-dos stay here.' +
        'Give it a home in Projects GTD',
    );
    expect(bar()).toBeUndefined();

    await act(async () => {
      button()!.click();
    });
    expect(api.createProjectLink).toHaveBeenCalledExactlyOnceWith(5);
    expect(card()).toBeNull();
    expect(bar()!.textContent).toBe('Board, files and messages are in Projects GTDOpen →');
    expect(bar()!.querySelector('a')!.getAttribute('href')).toBe(`${HERE}/projects/app/p/31/overview`);
  });

  it('is pressed once: the button is off while the request is out', async () => {
    await signIn();
    let finish!: (made: ProjectLink) => void;
    api.createProjectLink.mockReturnValue(new Promise<ProjectLink>((resolve) => (finish = resolve)));
    await show('/projects/5');
    await act(async () => {
      button()!.click();
    });
    expect(button()!.disabled).toBe(true);
    await act(async () => {
      button()!.click();
    });
    expect(api.createProjectLink).toHaveBeenCalledTimes(1);
    await act(async () => {
      finish(link());
    });
    expect(bar()).toBeDefined();
  });

  it('keeps the card and says why when the server refuses', async () => {
    await signIn();
    const why = 'Projects GTD already has a project named "Plan the fall menu". Rename one of the two, then try again.';
    api.createProjectLink.mockRejectedValue(new ApiError(400, why, `API error 400: ${why}`));
    await show('/projects/5');
    await act(async () => {
      button()!.click();
    });
    expect(card()!.querySelector('[role="alert"]')!.textContent).toBe(why);
    expect(button()!.disabled).toBe(false);
    expect(bar()).toBeUndefined();
  });

  it('does not carry a refusal over to the next project', async () => {
    await signIn();
    api.listProjects.mockResolvedValue([project(), project({ id: 6, name: 'Renew the certificate' })]);
    api.createProjectLink.mockRejectedValue(new ApiError(400, 'Refused.', 'API error 400: Refused.'));
    await show('/projects/5');
    await act(async () => {
      button()!.click();
    });
    expect(card()!.querySelector('[role="alert"]')).not.toBeNull();
    // The arrows keep the page mounted and change only the project it shows.
    await act(async () => {
      container.querySelector<HTMLAnchorElement>('a[aria-label="Next project"]')!.click();
    });
    expect(container.textContent).toContain('Renew the certificate');
    expect(card()).not.toBeNull();
    expect(card()!.querySelector('[role="alert"]')).toBeNull();
  });

  it('shows the bar, and no card, on a project that already has a home', async () => {
    await signIn();
    api.listProjectLinks.mockResolvedValue([link({ project_id: 4, board_id: 30 }), link()]);
    await show('/projects/5');
    expect(card()).toBeNull();
    expect(bar()!.querySelector('a')!.getAttribute('href')).toBe(`${HERE}/projects/app/p/31/overview`);
  });

  it('shows neither for a link to an archived Projects GTD project', async () => {
    await signIn();
    api.listProjectLinks.mockResolvedValue([link({ board_status: 'archived' })]);
    await show('/projects/5');
    expect(card()).toBeNull();
    expect(bar()).toBeUndefined();
  });

  it('shows neither on a dropped project, linked or not, and no card on a completed one', async () => {
    await signIn();
    api.listProjects.mockResolvedValue([
      project({ status: 'dropped' }),
      project({ id: 6, name: 'Dropped, no home', status: 'dropped' }),
      project({ id: 8, name: 'Finished, with a home', status: 'completed' }),
      project({ id: 9, name: 'Finished, no home', status: 'completed' }),
    ]);
    api.listProjectLinks.mockResolvedValue([
      link({ project_status: 'dropped' }),
      link({ project_id: 8, project_status: 'completed', board_id: 32 }),
    ]);
    for (const id of [5, 6, 9]) {
      await show(`/projects/${id}`);
      expect(card()).toBeNull();
      expect(bar()).toBeUndefined();
    }
    // A completed project keeps the way to its home.
    await show('/projects/8');
    expect(card()).toBeNull();
    expect(bar()!.querySelector('a')!.getAttribute('href')).toBe(`${HERE}/projects/app/p/32/overview`);
  });

  it("follows the project's status as it changes, without reading the links again", async () => {
    await signIn();
    api.listProjectLinks.mockResolvedValue([link()]);
    api.updateProject.mockResolvedValue(project());
    await show('/projects/5');
    expect(bar()).toBeDefined();

    // Dropped through the status selector: the project reloads, the links do not.
    api.listProjects.mockResolvedValue([project({ status: 'dropped' })]);
    const select = container.querySelector<HTMLSelectElement>('select[aria-label="Project status"]')!;
    await act(async () => {
      select.value = 'dropped';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(api.updateProject).toHaveBeenCalledWith(5, { status: 'dropped' });
    expect(select.value).toBe('dropped');
    expect(bar()).toBeUndefined();
    expect(card()).toBeNull();
    expect(api.listProjectLinks).toHaveBeenCalledTimes(1);
  });

  it('shows the bar once a project fetched as dropped is made active again', async () => {
    await signIn();
    api.listProjects.mockResolvedValue([project({ status: 'dropped' })]);
    api.listProjectLinks.mockResolvedValue([link({ project_status: 'dropped' })]);
    api.updateProject.mockResolvedValue(project());
    await show('/projects/5');
    expect(bar()).toBeUndefined();

    api.listProjects.mockResolvedValue([project()]);
    await act(async () => {
      [...container.querySelectorAll('button')].find((b) => b.textContent === 'Reactivate')!.click();
    });
    expect(api.updateProject).toHaveBeenCalledWith(5, { status: 'active' });
    expect(bar()!.querySelector('a')!.getAttribute('href')).toBe(`${HERE}/projects/app/p/31/overview`);
    expect(card()).toBeNull();
  });

  it('shows neither, and asks for nothing, with Projects GTD off for the account', async () => {
    await signIn(['todo']);
    api.listProjectLinks.mockResolvedValue([link()]);
    await show('/projects/5');
    expect(container.textContent).toContain('Plan the fall menu');
    expect(api.listProjectLinks).not.toHaveBeenCalled();
    expect(card()).toBeNull();
    expect(bar()).toBeUndefined();
  });

  it('shows neither when the links cannot be read: the page itself is unharmed', async () => {
    await signIn();
    api.listProjectLinks.mockRejectedValue(new Error('offline'));
    await show('/projects/5');
    expect(container.textContent).toContain('Plan the fall menu');
    expect(card()).toBeNull();
    expect(bar()).toBeUndefined();
  });
});

describe("Todo's Projects list", () => {
  const chips = () =>
    [...container.querySelectorAll('span')]
      .filter((s) => s.textContent === 'Board')
      .map((s) => s.closest('.relative.rounded-xl')!.querySelector('p')!.textContent);

  it('marks a project that has a home with a "Board" chip, and only a link that shows', async () => {
    await signIn();
    api.listProjects.mockResolvedValue([
      project(),
      project({ id: 6, name: 'Renew the certificate' }),
      project({ id: 8, name: 'Replace the cooler door' }),
    ]);
    api.listProjectLinks.mockResolvedValue([link(), link({ project_id: 8, board_id: 32, board_status: 'archived' })]);
    await show('/projects');
    expect(container.textContent).toContain('Replace the cooler door');
    expect(chips()).toEqual(['Plan the fall menu']);
  });

  it("puts the chip by the project's own status, not the one the link was read with", async () => {
    await signIn();
    api.listProjects.mockResolvedValue([
      project({ status: 'dropped' }),
      project({ id: 6, name: 'Renew the certificate' }),
    ]);
    api.listProjectLinks.mockResolvedValue([link(), link({ project_id: 6, board_id: 32, project_status: 'dropped' })]);
    await show('/projects');
    expect(container.textContent).toContain('Plan the fall menu');
    expect(chips()).toEqual(['Renew the certificate']);
  });

  it('has no chips with Projects GTD off for the account', async () => {
    await signIn(['todo']);
    api.listProjectLinks.mockResolvedValue([link()]);
    await show('/projects');
    expect(container.textContent).toContain('Plan the fall menu');
    expect(chips()).toEqual([]);
    expect(api.listProjectLinks).not.toHaveBeenCalled();
  });
});
