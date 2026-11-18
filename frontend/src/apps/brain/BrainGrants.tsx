import { useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { brainName, useBrainSelection, refreshBrains } from '../todo-gtd/brainSelection';
import { getBrains, setLinkBrains } from './api';

/** Selection order is the grant order; an explicit move makes the first brain clear. */
export function BrainTicks({
  value,
  onChange,
  disabled = false,
}: {
  value: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
}) {
  const { brains } = useBrainSelection();
  const active = brains.filter((b) => b.status === 'active');
  const ordered = [
    ...value.map((id) => active.find((b) => b.id === id)).filter((b) => b !== undefined),
    ...active.filter((b) => !value.includes(b.id)),
  ];
  return (
    <fieldset disabled={disabled} className="min-w-0 space-y-2">
      <legend className="text-sm font-semibold">Brains</legend>
      {ordered.map((b) => (
        <div key={b.id} className="flex items-center gap-2 text-sm">
          <label className="flex min-w-0 flex-1 items-center gap-2">
            <input
              type="checkbox"
              checked={value.includes(b.id)}
              onChange={(e) => onChange(e.target.checked ? [...value, b.id] : value.filter((id) => id !== b.id))}
            />
            <span className="break-words">{brainName(b)}</span>
          </label>
          {value.includes(b.id) && (
            <>
              <span className="text-xs text-muted">{value.indexOf(b.id) + 1}</span>
              <button
                type="button"
                className="cb-btn-ghost text-xs"
                aria-label={`Move ${brainName(b)} up`}
                disabled={value.indexOf(b.id) === 0}
                onClick={() => {
                  const next = [...value];
                  const i = next.indexOf(b.id);
                  [next[i - 1], next[i]] = [next[i], next[i - 1]];
                  onChange(next);
                }}
              >
                ↑
              </button>
            </>
          )}
        </div>
      ))}
    </fieldset>
  );
}
export function MainLinkBrains() {
  const [ids, setIds] = useState<number[] | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    getBrains().then(
      (d) => {
        refreshBrains(d.brains);
        setIds(d.link_brains);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load the link’s brains.')),
    );
  }, []);
  const save = async () => {
    if (!ids) return;
    setBusy(true);
    setError('');
    try {
      await setLinkBrains(ids);
      setSaved(true);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save brains.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="cb-panel space-y-3 p-5">
      <h2 className="font-heading text-lg font-bold text-white">Your main agent link</h2>
      <p className="text-sm text-muted">
        Choose its brains in order. The first catches memories without a destination.
      </p>
      {ids && (
        <>
          <BrainTicks
            value={ids}
            onChange={(v) => {
              setIds(v);
              setSaved(false);
            }}
            disabled={busy}
          />
          <button className="cb-btn text-sm" type="button" disabled={busy} onClick={() => void save()}>
            Save link brains
          </button>
        </>
      )}
      {saved && <p role="status">Saved</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
