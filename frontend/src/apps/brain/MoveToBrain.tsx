import { useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { brainName, useBrainSelection } from '../todo-gtd/brainSelection';
import { moveToBrain } from './api';
import { brainField } from './BrainsSection';

export function MoveToBrain({
  kind,
  id,
  version,
  path,
  onMoved,
}: {
  kind: 'memory' | 'page';
  id: number;
  version: number;
  path?: string;
  onMoved: () => void;
}) {
  const selection = useBrainSelection();
  const destinations = selection.brains.filter((b) => b.id !== selection.id && b.status === 'active');
  const [open, setOpen] = useState(false);
  const [to, setTo] = useState(destinations[0]?.id ?? 0);
  const [newPath, setNewPath] = useState(path ?? '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  if (!destinations.length) return null;
  const move = async () => {
    setBusy(true);
    setError('');
    try {
      await moveToBrain(kind, id, to, version, kind === 'page' ? newPath : undefined);
      onMoved();
      setOpen(false);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not move it.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="min-w-0">
      <button type="button" className="cb-btn-ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
        Move to brain…
      </button>
      {open && (
        <div className="mt-2 space-y-2 rounded-lg border border-line bg-cream p-3 text-charcoal">
          <label className="block text-sm">
            Destination brain
            <select className={brainField} value={to} onChange={(e) => setTo(Number(e.target.value))}>
              {destinations.map((b) => (
                <option key={b.id} value={b.id}>
                  {brainName(b)}
                </option>
              ))}
            </select>
          </label>
          {kind === 'page' && (
            <label className="block text-sm">
              Destination path
              <input className={brainField} value={newPath} onChange={(e) => setNewPath(e.target.value)} />
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="cb-btn"
              disabled={busy || !to || (kind === 'page' && !newPath.trim())}
              onClick={() => void move()}
            >
              Move
            </button>
            <button type="button" className="cb-btn-ghost" disabled={busy} onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
          {error && <p role="alert">{error}</p>}
        </div>
      )}
    </div>
  );
}
