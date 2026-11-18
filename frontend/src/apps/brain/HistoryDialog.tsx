// Common Brain — every version of a memory or a page, newest first, each with who
// made it and when; any older one can be brought back (as one more version).
import { useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { getHistory, restore } from './api';
import type { Version } from './types';
import { ACTIONS, ago, who } from './util';

export function HistoryDialog({
  kind,
  id,
  onClose,
  onRestored,
}: {
  kind: 'memory' | 'page';
  id: number;
  onClose: () => void;
  onRestored: () => void;
}) {
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    getHistory(kind, id).then(setVersions, (e) => setError(apiErrorMessage(e, 'Could not load the history.')));
  }, [kind, id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const back = async (v: Version) => {
    try {
      await restore(kind, id, v.version);
      onRestored();
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not restore it.'));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-3 sm:items-center" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="History"
        className="cb-glow max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-2xl p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-lg font-bold text-white">History</h2>
          <button type="button" onClick={onClose} className="cb-btn-ghost text-sm">
            Close
          </button>
        </div>
        <p className="mt-1 text-sm text-muted">
          Every version, newest first. Bringing one back keeps everything in between.
        </p>
        {error && (
          <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
            {error}
          </p>
        )}
        <ol className="mt-4 space-y-3">
          {(versions ?? []).map((v, i) => (
            <li key={v.version} className="cb-panel p-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <span className="font-semibold text-[#22d3ee]">v{v.version}</span>
                <span>
                  {who(v.by)} {ACTIONS[v.action] ?? v.action} it · {ago(v.at)}
                </span>
                {v.status === 'archived' && <span className="rounded bg-white/10 px-1.5">archived</span>}
                {v.locked && <span aria-label="locked">🔒</span>}
                {i > 0 && (
                  <button type="button" onClick={() => void back(v)} className="cb-btn-ghost ml-auto px-3 py-1 text-xs">
                    Bring this back
                  </button>
                )}
              </div>
              <div className="mt-1.5 whitespace-pre-wrap break-words text-sm text-charcoal">
                {kind === 'memory'
                  ? v.text
                  : `${v.title} (${v.path})\n\n${(v.body ?? '').slice(0, 600)}${(v.body ?? '').length > 600 ? '…' : ''}`}
              </div>
            </li>
          ))}
        </ol>
        {versions === null && !error && <p className="mt-4 text-sm text-muted">Loading…</p>}
      </div>
    </div>
  );
}
