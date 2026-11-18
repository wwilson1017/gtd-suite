import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { InlineTitle } from '../../shared/inline-edit';
import { createArea, listAreas, listProjects, listTodos, updateArea } from './api';
import { TodoEditSheet } from './components/TodoEditSheet';
import { TodoRow } from './components/TodoRow';
import { useRowActions, useTodosChanged } from './hooks';
import { todoPath } from './publicMode';
import { EmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo, TodoArea, TodoProject } from './types';
import { useTodoMeta } from './useTodoMeta';

const h3Cls = 'mb-2 mt-4 text-xs font-heading font-bold uppercase tracking-wide text-muted';
const smallBtnCls =
  'shrink-0 rounded-lg border border-line px-2.5 py-1.5 text-xs font-heading text-muted hover:bg-sand hover:text-charcoal';

/** Areas of focus — the standing parts of a life or job (Health, Family, the day
 *  job). Each shows what is live under it: active projects, next actions and
 *  someday items. A todo in a project sits under its project's area unless it
 *  has its own. Nothing is deleted: an area is archived and can be restored. */
export function AreasPage() {
  const [areas, setAreas] = useState<TodoArea[] | null>(null);
  const [projects, setProjects] = useState<TodoProject[]>([]);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const meta = useTodoMeta();

  const [loadSeq, setLoadSeq] = useState(0);
  const reload = useCallback(() => {
    setLoadSeq((s) => s + 1);
  }, []);
  useTodosChanged(reload);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listAreas(),
      listProjects('active'),
      listTodos({ status: 'next_action', limit: 500 }),
      listTodos({ status: 'someday_maybe', limit: 500 }),
    ])
      .then(([a, p, next, someday]) => {
        if (cancelled) return;
        setAreas(a);
        setProjects(p);
        setTodos([...next, ...someday]);
        setFailed(false);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [loadSeq]);

  const { toggleDone, toggleStar, after } = useRowActions(reload);

  /** One area write. Resolving false keeps an inline editor open on what was typed. */
  const write = async (run: () => Promise<unknown>): Promise<boolean> => {
    setError('');
    try {
      await run();
      after(); // reloads this page and the shared meta the area pickers read
      return true;
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save. Your change was not stored.'));
      return false;
    }
  };

  const add = async () => {
    if (!name.trim()) return;
    if (await write(() => createArea({ name: name.trim() }))) setName('');
  };

  const rows = (items: Todo[]) => (
    <div className="space-y-2">
      {items.map((t) => (
        <TodoRow key={t.id} todo={t} onToggleDone={toggleDone} onToggleStar={toggleStar} onEdit={setEditTodo} />
      ))}
    </div>
  );

  const active = (areas ?? []).filter((a) => a.status === 'active');
  const archived = (areas ?? []).filter((a) => a.status === 'dropped');

  return (
    <TodoShell active="areas" onAdded={reload}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
        className="mb-4 flex gap-2"
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Add an area of focus — Health, Family, Finances…"
          aria-label="New area name"
          className="min-w-0 flex-1 rounded-lg border border-line bg-cream px-3 py-2 text-base sm:text-sm text-charcoal placeholder:text-muted focus:border-brand focus:outline-none"
        />
        <button
          type="submit"
          disabled={!name.trim()}
          className="shrink-0 rounded-lg bg-brand-dark px-4 py-2 text-sm font-heading text-white hover:bg-brand-deep disabled:opacity-40"
        >
          Add
        </button>
      </form>
      {error && (
        <p role="alert" className="mb-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {failed && <LoadFailed retry={reload} />}
      {!failed && areas === null && <LoadingRows />}
      {!failed && areas !== null && areas.length === 0 && (
        <EmptyState
          title="No areas yet"
          hint="An area is a part of your life you keep up rather than finish. Add one, then pick it on a project or a todo."
        />
      )}

      <div className="space-y-4">
        {active.map((area) => {
          const areaProjects = projects.filter((p) => p.area_id === area.id);
          const mine = todos.filter((t) => t.effective_area_id === area.id);
          const next = mine.filter((t) => t.status === 'next_action');
          const someday = mine.filter((t) => t.status === 'someday_maybe');
          return (
            <section key={area.id} data-area={area.name} className="rounded-xl border border-line-faint bg-cream p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 grow">
                  <h2 className="font-heading text-lg font-bold text-charcoal">
                    <InlineTitle
                      title={area.name}
                      label="Area name"
                      onSave={(value) => write(() => updateArea(area.id, { name: value }))}
                      onCancel={() => setError('')}
                      className="-ml-1 font-heading text-lg font-bold text-charcoal"
                    />
                  </h2>
                  <InlineTitle
                    title={area.notes}
                    label="Area notes"
                    variant="body"
                    placeholder="Add notes…"
                    onSave={(value) => write(() => updateArea(area.id, { notes: value }))}
                    onCancel={() => setError('')}
                    className="-ml-1 whitespace-pre-wrap text-sm text-muted"
                  />
                </div>
                <button
                  type="button"
                  className={smallBtnCls}
                  title="Archive this area. Its projects and todos stay where they are."
                  onClick={() => void write(() => updateArea(area.id, { status: 'dropped' }))}
                >
                  Archive
                </button>
              </div>

              {areaProjects.length + mine.length === 0 && (
                <p className="mt-3 text-sm text-muted">
                  Nothing live here yet — pick this area on a project or a todo.
                </p>
              )}
              {areaProjects.length > 0 && (
                <>
                  <h3 className={h3Cls}>Projects</h3>
                  <ul className="space-y-1">
                    {areaProjects.map((p) => (
                      <li key={p.id}>
                        <Link
                          to={todoPath(`/projects/${p.id}`)}
                          className="flex items-center justify-between gap-2 rounded-lg border border-line-faint px-3 py-2 text-sm text-charcoal hover:border-brand/40"
                        >
                          <span className="min-w-0 break-words">{p.name}</span>
                          <span className="shrink-0 rounded-full bg-sand px-2 py-0.5 text-xs text-muted">
                            {p.open_count} open
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {next.length > 0 && (
                <>
                  <h3 className={h3Cls}>Next actions</h3>
                  {rows(next)}
                </>
              )}
              {someday.length > 0 && (
                <>
                  <h3 className={h3Cls}>Someday</h3>
                  {rows(someday)}
                </>
              )}
            </section>
          );
        })}
      </div>

      {archived.length > 0 && (
        <section className="mt-6">
          <h2 className={h3Cls}>Archived areas</h2>
          <ul className="space-y-1">
            {archived.map((area) => (
              <li
                key={area.id}
                className="flex items-center justify-between gap-2 rounded-lg border border-line-faint bg-cream px-3 py-2 text-sm text-muted"
              >
                <span className="min-w-0 break-words">{area.name}</span>
                <button
                  type="button"
                  className={smallBtnCls}
                  onClick={() => void write(() => updateArea(area.id, { status: 'active' }))}
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {editTodo && (
        <TodoEditSheet
          todo={editTodo}
          projects={meta.projects}
          contexts={meta.filters?.contexts ?? []}
          onClose={() => setEditTodo(null)}
          onSaved={after}
        />
      )}
    </TodoShell>
  );
}
