// Projects GTD — the Card Table's wormholes (Basecamp 5's): a column of another
// project's table, standing at the end of this one. Drop a card on it and the card
// goes there. A table has at most four; closing one archives it.
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { createItem, listBoards } from './api';
import type { BoardSummary, Wormhole } from './types';

export function WormholeTarget({ hole, onDrop, onClose }: { hole: Wormhole; onDrop: () => void; onClose: () => void }) {
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        onDrop();
      }}
      aria-label={`Wormhole to ${hole.project_name}: ${hole.column_name}`}
      className={`flex w-[54px] shrink-0 flex-col items-center gap-2 rounded-sm border-2 border-dashed py-3 ${over ? 'border-bc-blue bg-bc-wash' : 'border-bc-line'}`}
    >
      <span aria-hidden>🌀</span>
      <Link
        to={`/p/${hole.project_id}/cards`}
        className="text-[12px] font-semibold text-bc-subtle [writing-mode:vertical-rl] hover:underline"
      >
        {hole.project_name} › {hole.column_name}
      </Link>
      <button
        type="button"
        aria-label={`Close the wormhole to ${hole.project_name}`}
        onClick={onClose}
        className="text-[13px] text-bc-faint hover:text-bc-ink"
      >
        ×
      </button>
    </div>
  );
}

export function AddWormhole({ boardId, onDone }: { boardId: number; onDone: () => void }) {
  const [projects, setProjects] = useState<BoardSummary[]>([]);
  const [project, setProject] = useState('');
  const [column, setColumn] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    listBoards().then(
      (all) => setProjects(all.filter((p) => p.id !== boardId)),
      () => {},
    );
  }, [boardId]);
  const columns = projects.find((p) => String(p.id) === project)?.columns ?? [];
  const add = async () => {
    try {
      await createItem(boardId, 'wormhole', { column_id: Number(column) });
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not add the wormhole.'));
    }
  };
  return (
    <form
      className="mt-3 flex max-w-2xl flex-wrap items-center gap-2 rounded-lg border border-bc-line p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void add();
      }}
    >
      <p className="w-full text-[14px] text-bc-subtle">
        A wormhole stands at the end of this table: drop a card on it to send it to a column of another project.
      </p>
      <select
        value={project}
        onChange={(e) => {
          setProject(e.target.value);
          setColumn('');
        }}
        aria-label="Project"
        className="bc-input w-auto"
      >
        <option value="">Pick a project…</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      {project && (
        <select
          value={column}
          onChange={(e) => setColumn(e.target.value)}
          aria-label="Column"
          className="bc-input w-auto"
        >
          <option value="">Pick a column…</option>
          {columns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      )}
      <button type="submit" className="bc-btn bc-btn-primary" disabled={!column}>
        Add the wormhole
      </button>
      <button type="button" className="bc-btn" onClick={onDone}>
        Cancel
      </button>
      {error && (
        <p role="alert" className="w-full text-bc-unread">
          {error}
        </p>
      )}
    </form>
  );
}
