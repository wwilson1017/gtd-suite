// Projects GTD — Basecamp's bulk editing on To-dos: "Select to-dos…" puts a box on
// every open to-do; pick some and assign them, date them, move them to a list,
// complete or archive them all at once.
import { createContext, useContext, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { completeItem, moveItem, updateItem, type Todoset } from './api';
import { usePeople } from './ProjectsShell';
import type { Item } from './types';

export interface TodoSelect {
  selecting: boolean;
  selected: number[];
  toggle: (id: number) => void;
}
export const TodoSelectCtx = createContext<TodoSelect>({ selecting: false, selected: [], toggle: () => {} });
export const useTodoSelect = () => useContext(TodoSelectCtx);

/** Every open to-do on the page: loose ones, those in lists, and those in groups. */
export function openTodos(set: Todoset): Item[] {
  return [
    ...set.loose,
    ...set.lists.flatMap((l) =>
      l.children.flatMap((k) => (k.type === 'todo' ? [k] : k.type === 'todolist_group' ? (k.todos ?? []) : [])),
    ),
  ];
}

export function TodoSelectionBar({
  set,
  selected,
  onDone,
}: {
  set: Todoset;
  selected: number[];
  onDone: (cleared: boolean) => void;
}) {
  const { people } = usePeople();
  const [due, setDue] = useState('');
  const [error, setError] = useState('');
  const todos = openTodos(set).filter((t) => selected.includes(t.id));
  // One write per to-do, in turn; the page reloads once after.
  const each = async (write: (t: Item) => Promise<unknown>, fallback: string) => {
    try {
      for (const t of todos) await write(t);
      setError('');
      onDone(true);
    } catch (e) {
      setError(apiErrorMessage(e, fallback));
      onDone(false);
    }
  };
  const pick = 'bc-input w-auto py-1 text-[14px]';
  return (
    <div
      role="region"
      aria-label="Selected to-dos"
      className="sticky top-2 z-10 mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-bc-blue bg-bc-canvas p-2 shadow"
    >
      <span className="font-bold">{todos.length} selected</span>
      <select
        value=""
        aria-label="Assign the selected to-dos to"
        className={pick}
        disabled={!todos.length}
        onChange={(e) => {
          const who = e.target.value; // a person's id, or 'me' (made on first use, as AddTodo does)
          const has = (t: Item) => t.assignees.some((a) => (who === 'me' ? a.kind === 'me' : String(a.id) === who));
          if (who)
            void each(
              (t) =>
                has(t)
                  ? Promise.resolve()
                  : updateItem(t.id, {
                      assignee_ids: [...t.assignees.map((a) => a.id), who === 'me' ? 'me' : Number(who)],
                    }),
              'Could not assign them all.',
            );
        }}
      >
        <option value="">Assign to…</option>
        {!people.some((p) => p.kind === 'me') && <option value="me">Me</option>}
        {people.map((p) => (
          <option key={p.id} value={p.kind === 'me' ? 'me' : p.id}>
            {p.name}
            {p.kind === 'ai' ? ' (AI)' : ''}
          </option>
        ))}
      </select>
      <input
        type="date"
        value={due}
        onChange={(e) => setDue(e.target.value)}
        aria-label="Due date for the selected to-dos"
        className={pick}
      />
      <button
        type="button"
        className="bc-btn bc-btn-sm"
        disabled={!due || !todos.length}
        onClick={() => void each((t) => updateItem(t.id, { due_on: due }), 'Could not date them all.')}
      >
        Set due
      </button>
      {set.lists.length > 0 && (
        <select
          value=""
          aria-label="Move the selected to-dos to"
          className={pick}
          disabled={!todos.length}
          onChange={(e) => {
            const to = Number(e.target.value);
            if (to) void each((t) => moveItem(t.id, { parent_id: to }), 'Could not move them all.');
          }}
        >
          <option value="">Move to…</option>
          {set.lists.map((l) => (
            <option key={l.id} value={l.id}>
              {l.title}
            </option>
          ))}
        </select>
      )}
      <button
        type="button"
        className="bc-btn bc-btn-sm"
        disabled={!todos.length}
        onClick={() => void each((t) => completeItem(t.id, true), 'Could not complete them all.')}
      >
        Complete
      </button>
      <button
        type="button"
        className="bc-btn bc-btn-sm"
        disabled={!todos.length}
        onClick={() => {
          if (confirm(`Archive ${todos.length} to-do${todos.length === 1 ? '' : 's'}?`))
            void each((t) => updateItem(t.id, { status: 'archived' }), 'Could not archive them all.');
        }}
      >
        Archive
      </button>
      <button type="button" className="ml-auto text-[14px] text-bc-blue underline" onClick={() => onDone(true)}>
        Done selecting
      </button>
      {error && (
        <p role="alert" className="w-full text-bc-unread">
          {error}
        </p>
      )}
    </div>
  );
}
