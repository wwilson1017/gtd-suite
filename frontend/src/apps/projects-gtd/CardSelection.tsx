// Projects GTD — Trello's multi-select on the Card Table: Shift-, Cmd- or Ctrl-click
// cards (up to 20) and act on them all at once; Esc lets go.
import { useState } from 'react';
import { moveCard, updateCard } from './api';
import type { Board, Card } from './types';

export const MAX_SELECTED = 20;

/** The selection after a modified click on `id`: in or out, never past MAX_SELECTED. */
export function toggleSelected(selected: number[], id: number): number[] {
  if (selected.includes(id)) return selected.filter((i) => i !== id);
  return selected.length >= MAX_SELECTED ? selected : [...selected, id];
}

export function SelectionBar({
  board,
  selected,
  act,
  onClear,
}: {
  board: Board;
  selected: number[];
  act: (write: () => Promise<unknown>, fallback: string) => Promise<void>;
  onClear: () => void;
}) {
  const [due, setDue] = useState('');
  const cards = board.columns.flatMap((c) => c.cards).filter((c) => selected.includes(c.id));
  // One write per card, in turn; the board reloads once after.
  const each = (write: (c: Card) => Promise<unknown>, fallback: string) =>
    void act(async () => {
      for (const c of cards) await write(c);
      onClear();
    }, fallback);
  const pick = 'bc-input w-auto py-1 text-[14px]';
  return (
    <div
      role="region"
      aria-label="Selected cards"
      className="sticky top-2 z-10 mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-bc-blue bg-bc-canvas p-2 shadow"
    >
      <span className="font-bold">{cards.length} selected</span>
      <select
        value=""
        aria-label="Move the selected cards to"
        className={pick}
        onChange={(e) => {
          const to = Number(e.target.value);
          if (to) each((c) => moveCard(c.id, to), 'Could not move them all.');
        }}
      >
        <option value="">Move to…</option>
        {board.columns.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="bc-btn bc-btn-sm"
        onClick={() =>
          each(
            (c) =>
              (c.assignees ?? []).some((p) => p.kind === 'me')
                ? Promise.resolve()
                : updateCard(c.id, { assignee_ids: [...(c.assignees ?? []).map((p) => p.id), 'me'] }),
            'Could not assign them all.',
          )
        }
      >
        Assign to me
      </button>
      {(board.labels?.length ?? 0) > 0 && (
        <select
          value=""
          aria-label="Label the selected cards"
          className={pick}
          onChange={(e) => {
            const label = Number(e.target.value);
            if (label)
              each(
                (c) => updateCard(c.id, { labels: [...new Set([...(c.labels ?? []).map((l) => l.id), label])] }),
                'Could not label them all.',
              );
          }}
        >
          <option value="">Add a label…</option>
          {board.labels!.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name || l.color}
            </option>
          ))}
        </select>
      )}
      <input
        type="date"
        value={due}
        onChange={(e) => setDue(e.target.value)}
        aria-label="Due date for the selected cards"
        className={pick}
      />
      <button
        type="button"
        className="bc-btn bc-btn-sm"
        disabled={!due}
        onClick={() => each((c) => updateCard(c.id, { due_date: due }), 'Could not date them all.')}
      >
        Set due
      </button>
      <button
        type="button"
        className="bc-btn bc-btn-sm"
        onClick={() => {
          if (confirm(`Archive ${cards.length} card${cards.length === 1 ? '' : 's'}?`))
            each((c) => updateCard(c.id, { status: 'archived' }), 'Could not archive them all.');
        }}
      >
        Archive
      </button>
      <button type="button" className="ml-auto text-[14px] text-bc-blue underline" onClick={onClear}>
        Let go (Esc)
      </button>
    </div>
  );
}
