// Projects GTD — a project's labels (Trello's): name and colour each, add one,
// archive one (nothing is deleted; an archived label leaves every card it was on).
import { useCallback, useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { createLabel, listLabels, updateLabel } from './api';
import type { Label } from './types';
import { ColorPicker } from './ui';

export function LabelsEditor({ boardId, onClose }: { boardId: number; onClose: () => void }) {
  const [labels, setLabels] = useState<Label[] | null>(null);
  const [name, setName] = useState('');
  const [color, setColor] = useState('green');
  const [picking, setPicking] = useState<number | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    listLabels(boardId).then(setLabels, (e) => setError(apiErrorMessage(e, 'Could not load labels.')));
  }, [boardId]);
  useEffect(load, [load]);
  const run = (write: () => Promise<unknown>) =>
    void write().then(load, (e) => setError(apiErrorMessage(e, 'That did not save.')));
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Labels"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl bg-bc-canvas p-5 text-bc-ink shadow-xl sm:max-w-md sm:rounded-2xl"
      >
        <div className="flex items-center">
          <h2 className="text-xl font-bold">Labels</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto text-2xl leading-none text-bc-subtle"
          >
            &times;
          </button>
        </div>
        <ul className="mt-3 space-y-2">
          {labels?.map((l) => (
            <li key={l.id}>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-label={`Colour of ${l.name || 'label'}`}
                  onClick={() => setPicking(picking === l.id ? null : l.id)}
                  className={`bc-c-${l.color} h-8 w-12 shrink-0 rounded`}
                  style={{ background: 'var(--c)' }}
                />
                <input
                  defaultValue={l.name}
                  aria-label="Label name"
                  maxLength={100}
                  placeholder="(no name)"
                  onBlur={(e) => {
                    if (e.target.value.trim() !== l.name) run(() => updateLabel(l.id, { name: e.target.value.trim() }));
                  }}
                  className="bc-input py-1 text-[15px]"
                />
                <button
                  type="button"
                  className="text-[13px] text-bc-subtle underline"
                  onClick={() => run(() => updateLabel(l.id, { status: 'archived' }))}
                >
                  Archive
                </button>
              </div>
              {picking === l.id && (
                <div className="mt-2">
                  <ColorPicker
                    value={l.color}
                    onChange={(c) => {
                      setPicking(null);
                      run(() => updateLabel(l.id, { color: c }));
                    }}
                  />
                </div>
              )}
            </li>
          ))}
          {labels?.length === 0 && (
            <li className="text-[15px] text-bc-subtle">
              No labels yet. Add one below, or type a new name on any card.
            </li>
          )}
        </ul>
        <form
          className="mt-4 border-t border-bc-line pt-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) {
              run(() => createLabel(boardId, name.trim(), color));
              setName('');
            }
          }}
        >
          <p className="text-sm font-semibold">New label</p>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name it: Bug, Waiting, Design…"
            aria-label="New label name"
            maxLength={100}
            className="bc-input mt-1"
          />
          <div className="mt-2">
            <ColorPicker value={color} onChange={setColor} />
          </div>
          <button type="submit" className="bc-btn bc-btn-primary mt-3" disabled={!name.trim()}>
            Add label
          </button>
        </form>
        {error && (
          <p role="alert" className="mt-2 text-sm text-bc-unread">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
