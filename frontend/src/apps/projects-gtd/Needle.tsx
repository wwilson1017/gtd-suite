// Projects GTD — the Needle, as Basecamp's: how the project is going, set by
// hand (On track, Some risk, Concerned) with a note, every reading kept. It sits
// under the project's name; Mission Control (Reports) lists every project's.
import { useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { createItem, getNeedles } from './api';
import type { Item, Needle as NeedleValue } from './types';
import { Avatar, when } from './ui';

export const NEEDLE: Record<NeedleValue, { label: string; color: string; angle: number }> = {
  on_track: { label: 'On track', color: '#56b66f', angle: -60 },
  some_risk: { label: 'Some risk', color: '#e9b60f', angle: 0 },
  concerned: { label: 'Concerned', color: '#fd6c44', angle: 60 },
};

/** The gauge: three bands and the needle pointing at one (or upright and grey when unset). */
export function Gauge({ value, size = 64 }: { value?: NeedleValue | null; size?: number }) {
  const band = (from: number, to: number, color: string) => {
    const r = 40;
    const at = (deg: number) => [50 + r * Math.sin((deg * Math.PI) / 180), 50 - r * Math.cos((deg * Math.PI) / 180)];
    const [x1, y1] = at(from);
    const [x2, y2] = at(to);
    return <path d={`M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`} stroke={color} strokeWidth={12} fill="none" />;
  };
  const angle = value ? NEEDLE[value].angle : 0;
  return (
    <svg
      viewBox="0 0 100 58"
      width={size}
      height={size * 0.58}
      role="img"
      aria-label={value ? NEEDLE[value].label : 'No reading yet'}
      opacity={value ? 1 : 0.35}
    >
      {band(-90, -30, NEEDLE.on_track.color)}
      {band(-30, 30, NEEDLE.some_risk.color)}
      {band(30, 90, NEEDLE.concerned.color)}
      {value && (
        <>
          <line
            x1={50}
            y1={50}
            x2={50}
            y2={16}
            stroke="var(--color-bc-ink)"
            strokeWidth={4}
            strokeLinecap="round"
            transform={`rotate(${angle} 50 50)`}
          />
          <circle cx={50} cy={50} r={5} fill="var(--color-bc-ink)" />
        </>
      )}
    </svg>
  );
}

/** Under the project's name: the latest reading; open it to move the Needle or read its history. */
export function NeedleBox({
  projectId,
  latest,
  onMoved,
}: {
  projectId: number;
  latest: Item | null;
  onMoved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [pick, setPick] = useState<NeedleValue | null>(null);
  const [note, setNote] = useState('');
  const [history, setHistory] = useState<Item[] | null>(null);
  const [error, setError] = useState('');
  const toggle = () => {
    setOpen((o) => !o);
    if (!history) getNeedles(projectId).then(setHistory, () => setHistory([]));
  };
  const save = async () => {
    if (!pick) return;
    try {
      await createItem(projectId, 'needle', { needle: pick, body: note });
      setPick(null);
      setNote('');
      setOpen(false);
      setHistory(null);
      onMoved();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not update the status.'));
    }
  };
  return (
    <div className="mx-auto mt-3 max-w-xl">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="mx-auto flex items-center gap-2 rounded-full px-3 py-1 hover:bg-bc-wash"
      >
        <Gauge value={latest?.needle} size={44} />
        <span className="text-[15px]">
          {latest?.needle ? (
            <>
              <b>{NEEDLE[latest.needle].label}</b> <span className="text-bc-subtle">· {when(latest.created_at)}</span>
            </>
          ) : (
            <span className="text-bc-subtle">Set the status: how is this project going?</span>
          )}
        </span>
      </button>
      {latest?.body && !open && <p className="mt-1 text-center text-[15px] text-bc-subtle">“{latest.body}”</p>}
      {open && (
        <div className="mt-2 rounded-lg border border-bc-line p-4 text-left">
          <p className="font-bold">Update the status</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(Object.keys(NEEDLE) as NeedleValue[]).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={pick === v}
                onClick={() => setPick(v)}
                className={`rounded-full border px-3 py-1 text-[15px] ${pick === v ? 'font-bold' : ''}`}
                style={{ borderColor: NEEDLE[v].color, background: pick === v ? NEEDLE[v].color + '33' : undefined }}
              >
                {NEEDLE[v].label}
              </button>
            ))}
          </div>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            maxLength={20000}
            aria-label="Why"
            placeholder="Why? (optional)"
            className="bc-input mt-2"
          />
          {error && (
            <p role="alert" className="mt-1 text-sm text-bc-unread">
              {error}
            </p>
          )}
          <div className="mt-2 flex gap-2">
            <button type="button" className="bc-btn bc-btn-primary" disabled={!pick} onClick={() => void save()}>
              Save
            </button>
            <button type="button" className="bc-btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
          {history && history.length > 0 && (
            <ul className="mt-4 space-y-2 border-t border-bc-line pt-3">
              {history.map((n) => (
                <li key={n.id} className="flex items-start gap-2 text-[15px]">
                  <Avatar person={n.creator} size={24} />
                  <span className="min-w-0">
                    <b style={{ color: n.needle ? NEEDLE[n.needle].color : undefined }}>
                      {n.needle ? NEEDLE[n.needle].label : ''}
                    </b>
                    <span className="text-bc-subtle">
                      {' '}
                      · {n.creator?.name} · {when(n.created_at)}
                    </span>
                    {n.body && <span className="block">{n.body}</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
