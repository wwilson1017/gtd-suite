// Projects GTD — Move and Copy, as Basecamp's ••• menu has them: pick a project,
// then where in it (a to-do's list or group, a document's folder, or the top of
// its tool). A move keeps the comments and history; a copy starts fresh and
// takes what is under it (a list's to-dos, a folder's documents).
import { useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { copyItem, getFolder, getTodoset, listBoards, moveItem } from './api';
import type { BoardSummary, Item } from './types';

type Spot = { label: string; parent_id?: number };

/** Where in a project the item can go. */
async function spotsIn(projectId: number, item: Item): Promise<Spot[]> {
  if (item.type === 'todo' || item.type === 'todolist_group') {
    const set = await getTodoset(projectId);
    const spots: Spot[] = item.type === 'todo' ? [{ label: 'Loose to-dos (no list)' }] : [];
    for (const l of set.lists) {
      spots.push({ label: l.title, parent_id: l.id });
      if (item.type === 'todo') {
        for (const g of l.children.filter((c) => c.type === 'todolist_group'))
          spots.push({ label: `${l.title} › ${g.title}`, parent_id: g.id });
      }
    }
    return spots;
  }
  if (item.type === 'document' || item.type === 'link' || item.type === 'vault') {
    const top = await getFolder(projectId);
    return [
      { label: 'The top of Docs' },
      ...top.items
        .filter((f) => f.type === 'vault' && f.id !== item.id)
        .map((f) => ({ label: `📁 ${f.title}`, parent_id: f.id })),
    ];
  }
  return [{ label: 'The top of its tool' }];
}

export function MoveCopyDialog({
  item,
  mode,
  onDone,
  onCancel,
}: {
  item: Item;
  mode: 'move' | 'copy';
  onDone: (made: Item) => void;
  onCancel: () => void;
}) {
  const [projects, setProjects] = useState<BoardSummary[]>([]);
  const [project, setProject] = useState(item.board_id);
  const [spots, setSpots] = useState<Spot[] | null>(null);
  const [spot, setSpot] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    listBoards().then(setProjects, () => {});
  }, []);
  const [previousDestination, setPreviousDestination] = useState({ project, item, mode });
  if (
    project !== previousDestination.project ||
    item !== previousDestination.item ||
    mode !== previousDestination.mode
  ) {
    setPreviousDestination({ project, item, mode });
    setSpots(null);
  }
  useEffect(() => {
    spotsIn(project, item).then(
      (s) => {
        setSpots(s);
        // Start where it is now, when that is one of the choices.
        const here = s.findIndex(
          (x) => (x.parent_id ?? null) === (item.parent_id ?? null) && project === item.board_id,
        );
        setSpot(here >= 0 && mode === 'copy' ? here : 0);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load that project.')),
    );
  }, [project, item, mode]);
  const go = async () => {
    const to = spots?.[spot];
    if (!to) return;
    try {
      const where = to.parent_id !== undefined ? { parent_id: to.parent_id } : { project_id: project };
      onDone(mode === 'copy' ? await copyItem(item.id, where) : await moveItem(item.id, where));
    } catch (e) {
      setError(apiErrorMessage(e, mode === 'copy' ? 'Could not copy it.' : 'Could not move it.'));
    }
  };
  return (
    <div
      role="dialog"
      aria-label={mode === 'copy' ? 'Copy' : 'Move'}
      className="mb-4 rounded-lg border border-bc-line bg-bc-wash p-4"
    >
      <p className="font-bold">
        {mode === 'copy' ? 'Copy' : 'Move'} “{item.title || 'this'}” to…
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <select
          value={project}
          onChange={(e) => setProject(Number(e.target.value))}
          aria-label="Project"
          className="bc-input w-auto py-1"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          value={spot}
          onChange={(e) => setSpot(Number(e.target.value))}
          aria-label="Where"
          disabled={!spots}
          className="bc-input w-auto py-1"
        >
          {(spots ?? []).map((s, i) => (
            <option key={i} value={i}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {spots && spots.length === 0 && (
        <p className="mt-2 text-[14px] text-bc-subtle">That project has no to-do list to put it in yet.</p>
      )}
      {mode === 'move' && <p className="mt-2 text-[13px] text-bc-subtle">Its comments and history go with it.</p>}
      {mode === 'copy' && (
        <p className="mt-2 text-[13px] text-bc-subtle">The copy takes what is under it, but not the comments.</p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button type="button" className="bc-btn bc-btn-primary" disabled={!spots?.length} onClick={() => void go()}>
          {mode === 'copy' ? 'Copy it' : 'Move it'}
        </button>
        <button type="button" className="bc-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
