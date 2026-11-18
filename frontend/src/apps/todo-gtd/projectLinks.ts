// A Todo project's home in Projects GTD (backend/project_links.py), for Todo's pages.
import { useEffect, useState } from 'react';
import { listProjectLinks } from './api';
import { useSession } from './session';
import type { ProjectLink } from './types';

/** Whether a link shows at all: not to an archived Projects GTD project, and not
 *  from a dropped Todo project. Nothing is deleted, so the link itself stays. */
export function linkShown(link: ProjectLink): boolean {
  return link.board_status === 'active' && link.project_status !== 'dropped';
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
