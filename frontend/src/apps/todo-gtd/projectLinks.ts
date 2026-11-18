// A Todo project's home in Projects GTD (backend/project_links.py), for Todo's pages.
import { useEffect, useState } from 'react';
import { listProjectLinks } from './api';
import { useSession } from './session';
import type { ProjectLink, TodoProjectStatus } from './types';

/** Whether there is a link that shows: not to an archived Projects GTD project, and not
 *  from a dropped Todo project. `status` is the Todo project's status as the page holds
 *  it now (the link's own `project_status` is as it was when the links were read).
 *  Nothing is deleted, so the link itself stays. */
export function linkShown(link: ProjectLink | null | undefined, status: TodoProjectStatus): link is ProjectLink {
  return link?.board_status === 'active' && status !== 'dropped';
}

/** The account's links, while Projects GTD is on for it. `links` is null until they
 *  arrive, and stays null with Projects off or when they cannot be read: a link is an
 *  extra, and the page shows without it. `add` puts in one just made. */
export function useProjectLinks(): { links: ProjectLink[] | null; add: (made: ProjectLink) => void } {
  const on = useSession().session?.apps.includes('projects') ?? false;
  const [links, setLinks] = useState<ProjectLink[] | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    listProjectLinks().then(
      (all) => {
        if (live) setLinks(all);
      },
      () => {},
    );
    return () => {
      live = false;
    };
  }, [on]);
  const add = (made: ProjectLink) =>
    setLinks((all) => [...(all ?? []).filter((l) => l.project_id !== made.project_id), made]);
  return { links: on ? links : null, add };
}
