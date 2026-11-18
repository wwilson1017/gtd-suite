// Projects GTD — the To-dos tool, as Basecamp 5 lays it out: loose to-dos at the
// top, then each to-do list with its progress pie, its open to-dos and groups,
// "Add a to-do", and its completed ones folded away. A to-do drags to a new
// place in its list or into another list or group.
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { todayStr } from '../todo-gtd/util';
import {
  completeItem,
  createItem,
  getProject,
  getTodoset,
  importTodos,
  moveItem,
  shiftDates,
  type Todoset,
} from './api';
import { HillPanel } from './HillChart';
import { TodoSelectCtx, TodoSelectionBar, useTodoSelect } from './TodoSelection';
import { ProjectsShell, usePeople } from './ProjectsShell';
import type { Item, Project } from './types';
import { Avatar, Chip, Crumbs, day, EmptyState, Menu, Perma, ProgressPie } from './ui';

/** The id of the to-do being dragged, shared by every list on the page. */
let dragging: number | null = null;

export function TodoRow({
  todo,
  onChange,
  onDropBefore,
}: {
  todo: Item;
  onChange: () => void;
  onDropBefore?: (draggedId: number) => void;
}) {
  const today = todayStr();
  const overdue = !!todo.due_on && !todo.completed && todo.due_on < today;
  const pick = useTodoSelect(); // "Select to-dos…" on the To-dos page
  return (
    <li
      draggable={!!onDropBefore}
      onDragStart={(e) => {
        dragging = todo.id;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(todo.id));
      }}
      onDragOver={(e) => {
        if (onDropBefore) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (dragging && dragging !== todo.id) onDropBefore?.(dragging);
        dragging = null;
      }}
      className="group flex items-start gap-2.5 rounded-md py-1.5 hover:bg-bc-highlight/40 sm:px-1"
    >
      {pick.selecting && !todo.completed && (
        <input
          type="checkbox"
          checked={pick.selected.includes(todo.id)}
          onChange={() => pick.toggle(todo.id)}
          aria-label={`Select ${todo.title}`}
          className="mt-1 h-4 w-4 shrink-0 accent-bc-blue"
        />
      )}
      <input
        type="checkbox"
        className="bc-checkbox"
        checked={todo.completed}
        aria-label={todo.completed ? `Re-open ${todo.title}` : `Complete ${todo.title}`}
        onChange={() => void completeItem(todo.id, !todo.completed).then(onChange)}
      />
      <div className="min-w-0 flex-1 leading-snug">
        <Link
          to={`/i/${todo.id}`}
          className={`text-[17px] hover:underline ${todo.completed ? 'text-bc-subtle line-through' : ''}`}
        >
          {todo.title}
        </Link>
        <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
          {todo.assignees.length > 0 && (
            <Chip>
              {todo.assignees.slice(0, 3).map((a) => (
                <Avatar key={a.id} person={a} size={16} />
              ))}
              {todo.assignees.map((a) => a.name.split(' ')[0]).join(', ')}
            </Chip>
          )}
          {todo.due_on && (
            <Chip tone={overdue ? '!bg-[#ffede9] !text-[#cf432e]' : ''}>
              📅 {todo.starts_on ? `${day(todo.starts_on)} – ` : ''}
              {day(todo.due_on)}
            </Chip>
          )}
          {todo.body && <Chip>📝</Chip>}
          {todo.comments_count > 0 && <Chip>💬 {todo.comments_count}</Chip>}
        </span>
        {todo.completed && todo.completer && (
          <span className="ml-2 text-[13px] text-bc-faint">— {todo.completer.name}</span>
        )}
      </div>
    </li>
  );
}

/** "Add a to-do": a title, and who and when if you like. */
export function AddTodo({
  projectId,
  parentId,
  onAdded,
  label = 'Add a to-do',
}: {
  projectId: number;
  parentId?: number;
  onAdded: () => void;
  label?: string;
}) {
  const { people } = usePeople();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [who, setWho] = useState<string>('');
  const [due, setDue] = useState('');
  const [error, setError] = useState('');
  // One to-do as the form stands: its title, and whoever and whenever is picked.
  const addOne = (text: string) =>
    createItem(
      projectId,
      'todo',
      {
        title: text,
        ...(who ? { assignee_ids: [who === 'me' ? 'me' : Number(who)] } : {}),
        ...(due ? { due_on: due } : {}),
      },
      parentId ? { parent_id: parentId } : {},
    );
  const add = async () => {
    if (!title.trim()) return;
    try {
      await addOne(title.trim());
      setTitle('');
      setError('');
      onAdded();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not add the to-do.'));
    }
  };
  if (!open) {
    return (
      <button type="button" className="mt-1 text-[15px] text-bc-blue underline" onClick={() => setOpen(true)}>
        {label}
      </button>
    );
  }
  return (
    <form
      className="mt-2 rounded-lg border border-bc-line p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void add();
      }}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        placeholder="Describe this to-do… (paste a list to add several)"
        aria-label="To-do"
        maxLength={500}
        className="bc-input"
        onPaste={(e) => {
          const lines = pastedTodos(e.clipboardData.getData('text'));
          if (lines.length < 2 || !confirm(`Add ${lines.length} to-dos, one for each line?`)) return;
          e.preventDefault();
          void (async () => {
            try {
              for (const line of lines) {
                await addOne(line.slice(0, 500));
              }
              setError('');
            } catch (err) {
              setError(apiErrorMessage(err, 'Not all of them were added.'));
            }
            onAdded();
          })();
        }}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[15px]">
        <label className="flex items-center gap-1.5">
          <span className="text-bc-subtle">Assigned to</span>
          <select value={who} onChange={(e) => setWho(e.target.value)} className="bc-input w-auto py-1">
            <option value="">Nobody</option>
            {people.length === 0 && <option value="me">Me</option>}
            {people.map((p) => (
              <option key={p.id} value={p.kind === 'me' ? 'me' : p.id}>
                {p.name}
                {p.kind === 'ai' ? ' (AI)' : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-bc-subtle">Due on</span>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="bc-input w-auto py-1" />
        </label>
      </div>
      {error && (
        <p role="alert" className="mt-1 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <button type="submit" className="bc-btn bc-btn-primary" disabled={!title.trim()}>
          Add this to-do
        </button>
        <button type="button" className="bc-btn" onClick={() => setOpen(false)}>
          Done adding
        </button>
      </div>
    </form>
  );
}

/** Drop handler: put `dragged` just above the to-do `before` under `parentId`, or
 *  at the end of it ('bottom'). Naming the to-do, not an index, keeps the place
 *  right however many completed to-dos and groups the page hides. */
export async function dropTodo(
  dragged: number,
  parentId: number | undefined,
  before: number | 'bottom',
  reload: () => void,
) {
  if (parentId === undefined) return;
  await moveItem(
    dragged,
    before === 'bottom' ? { parent_id: parentId, position: 'bottom' } : { parent_id: parentId, before_id: before },
  );
  reload();
}

/** "✓ 3 completed": the completed to-dos, folded away until asked for (and re-openable). */
export function CompletedToggle({ todos, reload }: { todos: Item[]; reload: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        className="rounded-full border border-bc-green px-3 py-0.5 text-[14px] text-bc-green"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        ✓ {todos.length} completed
      </button>
      {open && (
        <ul className="mt-1">
          {todos.map((t) => (
            <TodoRow key={t.id} todo={t} onChange={reload} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** Basecamp's "Change dates": every open date in the list moves together. */
export async function changeDates(id: number, reload: () => void, say: (msg: string) => void = alert) {
  const answer = prompt(
    'Move every open date in this list by how many days? (A minus number moves them earlier.)',
    '7',
  );
  const days = Number(answer);
  if (answer === null || !Number.isInteger(days) || days === 0) return;
  try {
    const out = await shiftDates(id, days);
    say(
      `Moved ${out.shifted} date${out.shifted === 1 ? '' : 's'} ${days > 0 ? 'later' : 'earlier'} by ${Math.abs(days)} day${Math.abs(days) === 1 ? '' : 's'}.`,
    );
    reload();
  } catch (e) {
    say(apiErrorMessage(e, 'Could not move the dates.'));
  }
}

/** Several lines pasted at once: one to-do each (bullets and checkboxes dropped). */
export function pastedTodos(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.replace(/^\s*(?:[-*+•]|\d+[.)])?\s*(?:\[[ xX]?\])?\s*/, '').trim())
    .filter(Boolean);
}

function ListBlock({
  list,
  projectId,
  reload,
}: {
  list: Todoset['lists'][number];
  projectId: number;
  reload: () => void;
}) {
  const todos = list.children.filter((k) => k.type === 'todo');
  const groups = list.children.filter((k) => k.type === 'todolist_group');
  return (
    <section
      className={`bc-c-${list.color} mt-8`}
      aria-label={list.title}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        if (dragging) void dropTodo(dragging, list.id, 'bottom', reload);
        dragging = null;
      }}
    >
      <div className="flex items-center gap-2.5">
        <ProgressPie
          done={list.completed_count ?? 0}
          total={list.todos_count ?? 0}
          size={24}
          color={list.color ? 'var(--c)' : undefined}
        />
        <h2 className="text-[22px] font-bold leading-tight">
          <Link to={`/i/${list.id}`} className="hover:underline">
            {list.title}
          </Link>
        </h2>
        <span className="text-[14px] text-bc-subtle">
          {list.completed_count}/{list.todos_count} completed
        </span>
        <span className="ml-auto">
          <Menu items={[{ label: 'Change dates…', onClick: () => void changeDates(list.id, reload) }]} />
        </span>
      </div>
      {list.body && <p className="ml-9 mt-1 line-clamp-2 text-[15px] text-bc-subtle">{list.body}</p>}
      <ul className="ml-0 mt-2 sm:ml-7">
        {todos.map((t) => (
          <TodoRow
            key={t.id}
            todo={t}
            onChange={reload}
            onDropBefore={(d) => void dropTodo(d, list.id, t.id, reload)}
          />
        ))}
      </ul>
      {groups.map((g) => (
        <div
          key={g.id}
          className={`bc-c-${g.color} ml-0 mt-3 sm:ml-7`}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (dragging) void dropTodo(dragging, g.id, 'bottom', reload);
            dragging = null;
          }}
        >
          <h3
            className="border-b-2 pb-0.5 text-[16px] font-bold"
            style={{ borderColor: g.color ? 'var(--c)' : 'var(--color-bc-line)' }}
          >
            <Link to={`/i/${g.id}`} className="hover:underline">
              {g.title}
            </Link>
          </h3>
          <ul className="mt-1">
            {(g.todos ?? []).map((t) => (
              <TodoRow
                key={t.id}
                todo={t}
                onChange={reload}
                onDropBefore={(d) => void dropTodo(d, g.id, t.id, reload)}
              />
            ))}
          </ul>
          <AddTodo projectId={projectId} parentId={g.id} onAdded={reload} />
          {(g.completed_todos?.length ?? 0) > 0 && <CompletedToggle todos={g.completed_todos!} reload={reload} />}
        </div>
      ))}
      <div className="ml-0 sm:ml-7">
        <AddTodo projectId={projectId} parentId={list.id} onAdded={reload} />
        {list.completed_todos.length > 0 && <CompletedToggle todos={list.completed_todos} reload={reload} />}
      </div>
    </section>
  );
}

function NewList({ projectId, onDone }: { projectId: number; onDone: (made: boolean) => void }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const make = async () => {
    try {
      await createItem(projectId, 'todolist', { title: title.trim(), body });
      onDone(true);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not make the list.'));
    }
  };
  return (
    <form
      className="mt-4 rounded-lg border border-bc-line p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void make();
      }}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        placeholder="Name this list…"
        aria-label="List name"
        maxLength={500}
        className="bc-input text-[20px] font-bold"
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Add extra details or attach a link (optional)"
        aria-label="List notes"
        rows={2}
        maxLength={20000}
        className="bc-input mt-2"
      />
      {error && (
        <p role="alert" className="mt-1 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <button type="submit" className="bc-btn bc-btn-primary" disabled={!title.trim()}>
          Add this list
        </button>
        <button type="button" className="bc-btn" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** What an import added, in words. */
export function importSummary(n: { lists: number; groups: number; todos: number; subtasks: number }): string {
  const parts = (
    [
      [n.lists, 'list'],
      [n.groups, 'group'],
      [n.todos, 'to-do'],
      [n.subtasks, 'subtask'],
    ] as const
  )
    .filter(([k]) => k > 0)
    .map(([k, w]) => `${k} ${w}${k === 1 ? '' : 's'}`);
  return `Added ${parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : (parts[0] ?? 'nothing')}.`;
}

/** Basecamp's Markdown import: paste a plan, choose a file, or drop one on the page. */
function ImportTodos({
  projectId,
  text,
  setText,
  onDone,
}: {
  projectId: number;
  text: string;
  setText: (t: string) => void;
  onDone: (said: string) => void;
}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false); // one import at a time: a second click would add it all twice
  const go = async () => {
    if (busy) return;
    setBusy(true);
    try {
      onDone(importSummary(await importTodos(projectId, text)));
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not import that.'));
      setBusy(false);
    }
  };
  return (
    <form
      className="mt-3 rounded-lg border border-bc-line p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void go();
      }}
    >
      <p className="text-[14px] text-bc-subtle">
        Paste a plan in Markdown, or drop a .md or .txt file on this page: a # heading starts a to-do list, each line is
        a to-do, an indented line is a subtask of the one above, and "- [x]" adds one already done. Up to 500 lines.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={8}
        maxLength={20000}
        autoFocus
        aria-label="Markdown to import"
        className="bc-input mt-2 font-mono text-[14px]"
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="submit" className="bc-btn bc-btn-primary" disabled={!text.trim() || busy}>
          {busy ? 'Importing…' : 'Import'}
        </button>
        <button type="button" className="bc-btn" onClick={() => onDone('')}>
          Cancel
        </button>
        <input
          type="file"
          accept=".md,.markdown,.txt,text/markdown,text/plain"
          aria-label="Choose a file"
          className="text-[14px]"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void readPlan(f).then(setText, (err) => setError(String(err.message ?? err)));
          }}
        />
      </div>
      {error && (
        <p role="alert" className="mt-2 text-bc-unread">
          {error}
        </p>
      )}
    </form>
  );
}

/** A dropped or chosen plan's text, if it is small enough to import. */
function readPlan(file: File): Promise<string> {
  return file.size > 100_000
    ? Promise.reject(new Error('That file is too big to import (100 KB at most).'))
    : file.text();
}

export function TodosPage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [set, setSet] = useState<Todoset | null>(null);
  const [making, setMaking] = useState(false);
  const [importing, setImporting] = useState<string | null>(null); // the text, while the import is open
  const [selecting, setSelecting] = useState(false); // Basecamp's bulk editing (TodoSelection)
  const [selected, setSelected] = useState<number[]>([]);
  const toggle = (todoId: number) =>
    setSelected((s) => (s.includes(todoId) ? s.filter((i) => i !== todoId) : [...s, todoId]));
  const [note, setNote] = useState('');
  const [view, setView] = useState<'active' | 'archived'>('active');
  const [error, setError] = useState('');
  const load = useCallback(() => {
    getProject(id).then(setProject, (e) => setError(apiErrorMessage(e, 'Could not load this project.')));
    getTodoset(id, view).then(setSet, (e) => setError(apiErrorMessage(e, 'Could not load the to-dos.')));
  }, [id, view]);
  useEffect(load, [load]);

  const title = project?.dock.find((t) => t.tool === 'todoset')?.title ?? 'To-dos';
  const done = set?.lists.reduce((n, l) => n + (l.completed_count ?? 0), 0) ?? 0;
  const total = set?.lists.reduce((n, l) => n + (l.todos_count ?? 0), 0) ?? 0;

  return (
    <ProjectsShell project={project} title={`${title} · ${project?.name ?? ''}`}>
      <Perma>
        <TodoSelectCtx.Provider value={{ selecting, selected, toggle }}>
          <Crumbs
            project={project}
            crumbs={[{ label: project?.name ?? '…', to: `/p/${id}` }, { label: title }]}
            right={
              <Menu
                items={[
                  {
                    label: 'Import from Markdown…',
                    hidden: view !== 'active',
                    onClick: () => setImporting(importing ?? ''),
                  },
                  {
                    label: selecting ? 'Stop selecting' : 'Select to-dos…',
                    hidden: view !== 'active',
                    onClick: () => {
                      setSelecting(!selecting);
                      setSelected([]);
                    },
                  },
                  {
                    label: view === 'active' ? 'Archived lists' : 'Back to the lists',
                    onClick: () => setView((v) => (v === 'active' ? 'archived' : 'active')),
                  },
                ]}
              />
            }
          />
          <div
            onDragOver={(e) => {
              if (e.dataTransfer.types.includes('Files')) e.preventDefault();
            }}
            onDrop={(e) => {
              const file = e.dataTransfer.files[0];
              if (!file || view !== 'active') return;
              e.preventDefault();
              void readPlan(file).then(setImporting, (err) => setError(String(err.message ?? err)));
            }}
          >
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="bc-title text-2xl">{view === 'active' ? title : 'Archived lists'}</h1>
              {total > 0 && (
                <span className="text-bc-subtle">
                  {done}/{total} completed
                </span>
              )}
              {view === 'active' && (
                <button type="button" className="bc-btn bc-btn-primary ml-auto" onClick={() => setMaking(true)}>
                  ＋ New list
                </button>
              )}
            </div>
            {making && (
              <NewList
                projectId={id}
                onDone={(made) => {
                  setMaking(false);
                  if (made) load();
                }}
              />
            )}
            {importing !== null && (
              <ImportTodos
                projectId={id}
                text={importing}
                setText={setImporting}
                onDone={(said) => {
                  setImporting(null);
                  setNote(said);
                  if (said) load();
                }}
              />
            )}
            {note && (
              <p role="status" className="mt-3 text-bc-subtle">
                {note}
              </p>
            )}
            {selecting && set && view === 'active' && (
              <TodoSelectionBar
                set={set}
                selected={selected}
                onDone={(cleared) => {
                  if (cleared) {
                    setSelecting(false);
                    setSelected([]);
                  }
                  load();
                }}
              />
            )}
            {error && (
              <p role="alert" className="mt-3 text-bc-unread">
                {error}
              </p>
            )}
            {set && view === 'active' && (
              <HillPanel key={set.lists.map((l) => l.id).join()} projectId={id} lists={set.lists} />
            )}
            {set && view === 'active' && (
              <section aria-label="Loose to-dos" className="mt-6">
                <ul>
                  {set.loose.map((t) => (
                    <TodoRow key={t.id} todo={t} onChange={load} />
                  ))}
                </ul>
                <AddTodo projectId={id} onAdded={load} label={set.loose.length ? 'Add a to-do' : 'Add a loose to-do'} />
                {set.loose_completed.length > 0 && <CompletedToggle todos={set.loose_completed} reload={load} />}
              </section>
            )}
            {set && set.lists.length === 0 && set.loose.length === 0 && !making && (
              <div className="mt-6">
                <EmptyState title={view === 'active' ? 'No to-do lists yet.' : 'No archived lists.'}>
                  {view === 'active' &&
                    'Make a list for each piece of the work, then add to-dos, assign them and set due dates.'}
                </EmptyState>
              </div>
            )}
            {set?.lists.map((l) => (
              <ListBlock key={l.id} list={l} projectId={id} reload={load} />
            ))}
          </div>
        </TodoSelectCtx.Provider>
      </Perma>
    </ProjectsShell>
  );
}
