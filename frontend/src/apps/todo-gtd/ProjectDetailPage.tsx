import { Fragment, useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { createProjectLink, createTodo, listProjects, listTodos, updateProject } from './api';
import { PROJECT_STATUSES } from './constants';
import { useCrossAppHref } from './hop';
import { linkShown, useProjectLinks } from './projectLinks';
import { todoPath } from './publicMode';
import { updateProjectStatus } from './projectActions';
import { isTypingTarget, projectNeighbours } from './projectNav';
import { Logo } from './components/Logo';
import { TodoEditSheet } from './components/TodoEditSheet';
import { TodoRow } from './components/TodoRow';
import { useRowActions, useTodosChanged } from './hooks';
import { LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { Todo, TodoProject, TodoProjectStatus } from './types';
import { withOwnArea } from './util';
import { toast } from './toast';
import { refreshMeta, useTodoMeta } from './useTodoMeta';
import { InlineTitle } from '../../shared/inline-edit';
import { apiErrorMessage } from '../../core/api/client';

/** The project's inline-editable text fields. */
type Field = 'name' | 'notes' | 'purpose' | 'outcome';

// The two questions that turn a title into a project you can steer by.
const WHY_AND_WHAT: { field: 'purpose' | 'outcome'; heading: string; placeholder: string }[] = [
  { field: 'purpose', heading: 'Purpose', placeholder: 'Why does this matter?' },
  { field: 'outcome', heading: 'Outcome', placeholder: 'What does done look like?' },
];

const FINISHED = 'Finished';
const GROUPS: { title: string; match: (t: Todo) => boolean }[] = [
  { title: 'Next actions', match: (t) => t.status === 'next_action' },
  { title: 'Waiting / Delegated', match: (t) => t.status === 'waiting_for' || t.status === 'delegated' },
  { title: 'Someday', match: (t) => t.status === 'someday_maybe' },
  { title: 'Inbox', match: (t) => t.status === 'inbox' },
  { title: FINISHED, match: (t) => t.status === 'done' || t.status === 'dropped' },
];

/** The tint of what points at Projects GTD from here: its teal, as the page's other callouts are tinted. */
const PROJECTS_TINT = 'border-teal-300 bg-teal-50 dark:border-teal-800 dark:bg-teal-950/30';

export function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const [project, setProject] = useState<TodoProject | null>(null);
  const [todos, setTodos] = useState<Todo[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [newAction, setNewAction] = useState('');
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  /**
   * ONE failure line for both editable fields, TAGGED with the field it belongs to.
   *
   * The tag is not bookkeeping — without it the message can be wiped by the other field.
   * Both editors can be open at once (clicking the notes trigger is what blurs the name
   * editor, and a REFUSED name save leaves that editor open and pulls focus back to it), so
   * the name's focus recovery blurs the notes editor, which closes unchanged and would clear
   * the very refusal the name save had just reported — leaving the user's text on screen with
   * nothing to say why it did not save. Each field now only ever clears its own.
   */
  const [saveError, setSaveError] = useState<{ field: Field; text: string } | null>(null);
  /** Clear the line only if it belongs to `field` — see above. */
  const clearErrorFor = (field: Field) => setSaveError((e) => (e?.field === field ? null : e));
  const { projects, filters } = useTodoMeta();

  // Previous / next among projects of the same status, from the cached list.
  const navigate = useNavigate();
  const neighbours = projectNeighbours(projects, projectId);
  const prevId = neighbours?.prev;
  const nextId = neighbours?.next;
  const sheetOpen = editTodo !== null;
  useEffect(() => {
    if (prevId === undefined || nextId === undefined || sheetOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      // Never while typing (the title, notes, purpose and outcome edit in place).
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || isTypingTarget(e.target)) return;
      navigate(todoPath(`/projects/${e.key === 'ArrowLeft' ? prevId : nextId}`));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [prevId, nextId, sheetOpen, navigate]);

  const [loadSeq, setLoadSeq] = useState(0);
  const reload = useCallback(() => {
    setLoadSeq((s) => s + 1);
  }, []);
  // This page fetches its own project + todos rather than going through
  // `useTodos`, so it subscribes to the undo broadcast itself.
  useTodosChanged(reload);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listProjects(),
      // A project's own page shows its deferred todos too, each saying when it comes
      // back — this is a record view, not a working list.
      listTodos({ project: String(projectId), limit: 500, include_deferred: true }),
    ])
      .then(([allProjects, items]) => {
        if (cancelled) return;
        const p = allProjects.find((x) => x.id === projectId) ?? null;
        setProject(p);
        setTodos(items);
        setFailed(!p);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, loadSeq]);

  const { toggleDone, toggleStar, after } = useRowActions(reload);

  // Its home in Projects GTD: the link when it has one, and the way to make one.
  const { links, add: addLink } = useProjectLinks();
  const link = links?.find((l) => l.project_id === projectId) ?? null;
  const projectsHref = useCrossAppHref('projects');
  const [givingHome, setGivingHome] = useState(false);
  // Tagged with its project: the previous / next arrows keep this page mounted.
  const [homeRefused, setHomeRefused] = useState<{ project: number; why: string } | null>(null);
  const homeError = homeRefused?.project === projectId ? homeRefused.why : '';
  const giveHome = async () => {
    setGivingHome(true);
    setHomeRefused(null);
    try {
      addLink(await createProjectLink(projectId));
    } catch (e) {
      setHomeRefused({ project: projectId, why: apiErrorMessage(e, 'Could not make it. Try again.') });
    } finally {
      setGivingHome(false);
    }
  };

  const addNextAction = async () => {
    const title = newAction.trim();
    if (!title) return;
    try {
      await createTodo({ title, status: 'next_action', project_id: projectId });
    } catch (e) {
      // Keep the typed text: a refused add (list full, rate limit, offline) must not eat it.
      toast.error(apiErrorMessage(e, 'Could not add that. Try again.'));
      return;
    }
    // Clear only what was sent, never text typed while the add was in flight.
    setNewAction((cur) => (cur.trim() === title ? '' : cur));
    after();
  };

  const setProjectStatus = async (status: TodoProjectStatus) => {
    if (await updateProjectStatus(projectId, status)) after();
  };

  /**
   * Persist ONE project field.
   *
   * It merges back only the field it WROTE rather than adopting the whole response row, and
   * that is the load-bearing part. Both editors write through here and neither blocks the
   * other, so two PUTs can be in flight at once — and each resolves with the full row as the
   * server read it back. Adopting one wholesale therefore lets a slower response carry a
   * SIBLING field's pre-write value and revert an edit the user already watched save, with
   * the database holding the correct merged row and nothing on the page to correct it. The
   * response is still what supplies `updated_at`, and `open_count` is not read here (the
   * counts on this page come from its own todos array).
   *
   * `refreshMeta()` is what carries a rename off this page: the module-level meta cache is
   * what feeds the Projects list, the todo rows' project name and `TodoEditSheet`'s project
   * picker, and without it they keep showing the old name until a reload.
   *
   * Resolving FALSE is the contract with `InlineTitle` — the editor then stays open holding
   * what was typed, under the failure line this sets, rather than silently discarding the
   * user's text. Nothing is written locally on that path, so a value only ever appears as
   * saved once the server has stored it.
   */
  const saveField = async (field: Field, value: string): Promise<boolean> => {
    const fields = { [field]: value };
    clearErrorFor(field);
    try {
      const saved = await updateProject(projectId, fields);
      setProject((p) => (p ? { ...p, ...fields, updated_at: saved.updated_at } : saved));
      void refreshMeta();
      return true;
    } catch (e) {
      // The server's own `detail` is the message worth showing — the duplicate-name refusal
      // is `Project "Q4 launch" already exists`, which names the conflict and tells the user
      // what to type instead. `apiErrorMessage` is the platform's one unwrapper for that.
      setSaveError({ field, text: apiErrorMessage(e, 'Could not save. Your change was not stored.') });
      return false;
    }
  };

  /** The area is a pick, not typed text: write it, then reload the row (its `area_name`
   * and every todo that inherits the area come back with it). */
  const setArea = async (value: string) => {
    try {
      await updateProject(projectId, { area_id: value ? Number(value) : null });
      after();
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to update project.'));
    }
  };
  const areaOptions = withOwnArea(filters?.areas ?? [], project?.area_id, project?.area_name);

  const open = (todos ?? []).filter((t) => !['done', 'dropped'].includes(t.status));
  const hasNext = open.some((t) => t.status === 'next_action');
  const homeHref = project && linkShown(link, project.status) ? projectsHref(`/p/${link.board_id}/overview`) : null;
  // Offered only where the way there can be shown afterwards, and not on a closed project.
  const offerHome =
    links !== null &&
    !link &&
    projectsHref('') !== null &&
    (project?.status === 'active' || project?.status === 'someday');

  return (
    <TodoShell active="projects" onAdded={reload}>
      <div className="flex items-center justify-between gap-3">
        <Link to={todoPath('/projects')} className="text-sm text-muted hover:text-charcoal">
          ← All projects
        </Link>
        {neighbours && (
          <div className="flex gap-1">
            {(
              [
                ['Previous project', '←', neighbours.prev],
                ['Next project', '→', neighbours.next],
              ] as const
            ).map(([label, arrow, to]) => (
              <Link
                key={label}
                to={todoPath(`/projects/${to}`)}
                aria-label={label}
                title={label}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-cream text-muted hover:bg-sand hover:text-charcoal focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
              >
                <span aria-hidden="true">{arrow}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
      {failed && (
        <div className="mt-3">
          <LoadFailed retry={reload} />
        </div>
      )}
      {!failed && (project === null || todos === null) && <LoadingRows />}
      {project && todos !== null && (
        <>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            {/* `grow` is load-bearing, not spacing. This column used to hold a plain `<h2>`
                and so was sized to its text's max-content — which does NOT include the
                padding and border the click-to-edit trigger adds, so `InlineTitle`'s
                `max-w-full` capped the button ~10px short of its own single-line width and
                every multi-word project name broke at the last space. `grow` (basis auto, so
                it still wraps at the right point on a narrow screen — unlike `flex-1`'s basis
                of 0) lets the column take the free space that was already there. */}
            <div className="min-w-0 grow">
              {/* The heading stays an `<h2>` and the editor renders INSIDE it, so the page
                  keeps its heading semantics while the words themselves become the control
                  `-ml-1` cancels the
                  control's own padding so the text still lines up with the notes beneath. */}
              <h2 className="font-heading text-xl font-bold text-charcoal">
                <InlineTitle
                  title={project.name}
                  label="Project name"
                  onSave={(name) => saveField('name', name)}
                  // A blank name is refused by the control before it reaches the server, so
                  // this is the only place that refusal can be explained. Every other close
                  // (Escape, or nothing changed) just clears whatever line was up.
                  onCancel={(reason) =>
                    reason === 'blank'
                      ? setSaveError({
                          field: 'name',
                          text: 'A project name is required — the previous name was kept.',
                        })
                      : clearErrorFor('name')
                  }
                  className="-ml-1 font-heading text-xl font-bold text-charcoal"
                />
              </h2>
              {/* Always rendered, even with no notes: the placeholder IS the affordance, and
                  before this the element was absent entirely when blank — so a project with
                  no notes had nothing to click. */}
              <InlineTitle
                title={project.notes}
                label="Project notes"
                variant="body"
                placeholder="Add notes…"
                onSave={(notes) => saveField('notes', notes)}
                onCancel={() => clearErrorFor('notes')}
                className="-ml-1 mt-0.5 whitespace-pre-wrap text-sm text-muted"
              />
            </div>
            <div className="flex items-center gap-2">
              {project.status === 'completed' || project.status === 'dropped' ? (
                <button
                  type="button"
                  onClick={() => void setProjectStatus('active')}
                  className="rounded-lg border border-line bg-cream px-3 py-1.5 text-sm font-heading text-charcoal hover:bg-sand"
                >
                  Reactivate
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void setProjectStatus('completed')}
                  className="rounded-lg border border-green-600 px-3 py-1.5 text-sm font-heading text-green-700 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-950/30"
                >
                  ✓ Mark Completed
                </button>
              )}
              <select
                value={project.status}
                onChange={(e) => void setProjectStatus(e.target.value as TodoProjectStatus)}
                className="rounded-lg border border-line bg-cream px-2 py-1.5 text-sm capitalize text-charcoal focus:border-brand focus:outline-none"
                aria-label="Project status"
              >
                {PROJECT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              {areaOptions.length > 0 && (
                <select
                  value={project.area_id ?? ''}
                  onChange={(e) => void setArea(e.target.value)}
                  className="rounded-lg border border-line bg-cream px-2 py-1.5 text-sm text-charcoal focus:border-brand focus:outline-none"
                  aria-label="Project area"
                >
                  <option value="">No area</option>
                  {areaOptions.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {/* Always rendered, for the reason the notes are: the placeholder is the
              affordance on a project that has not answered the question yet. */}
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {WHY_AND_WHAT.map(({ field, heading, placeholder }) => (
              <div key={field} className="rounded-lg border border-line-faint bg-cream px-3 py-2">
                <h3 className="text-xs font-heading font-bold uppercase tracking-wide text-muted">{heading}</h3>
                <InlineTitle
                  title={project[field] ?? ''}
                  label={`Project ${field}`}
                  variant="body"
                  placeholder={placeholder}
                  onSave={(value) => saveField(field, value)}
                  onCancel={() => clearErrorFor(field)}
                  className="-ml-1 mt-0.5 whitespace-pre-wrap text-sm text-charcoal"
                />
              </div>
            ))}
          </div>

          {/* Under the header rather than inside it: a duplicate-name refusal names the
              conflicting project and needs the full width, and the flex row's other child is
              the status select. `role="alert"` because the eye is on the editor,
              which stays open above this with the typed text intact. */}
          {saveError && (
            <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
              {saveError.text}
            </p>
          )}

          {homeHref && (
            <p
              className={`mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border px-3 py-2 text-sm text-charcoal ${PROJECTS_TINT}`}
            >
              <Logo app="projects" className="h-5 w-5 shrink-0" />
              <span className="min-w-0 flex-1">
                <strong>Board, files and messages</strong> are in Projects GTD
              </span>
              <a href={homeHref} className="shrink-0 font-heading font-semibold text-projects-ink hover:underline">
                Open <span aria-hidden="true">→</span>
              </a>
            </p>
          )}

          {project.status === 'active' && !hasNext && (
            <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30 px-3 py-2 text-sm text-charcoal">
              This active project has <strong>no next action</strong> — decide the very next physical step, or it will
              stall.
            </p>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void addNextAction();
            }}
            className="mt-4 flex gap-2"
          >
            <input
              value={newAction}
              onChange={(e) => setNewAction(e.target.value)}
              placeholder="Add a next action to this project…"
              className="min-w-0 flex-1 rounded-lg border border-line bg-cream px-3 py-2 text-base sm:text-sm text-charcoal placeholder:text-muted focus:border-brand focus:outline-none"
            />
            <button
              type="submit"
              disabled={!newAction.trim()}
              className="shrink-0 rounded-lg bg-brand-dark px-4 py-2 text-sm font-heading text-white hover:bg-brand-deep disabled:opacity-40"
            >
              Add
            </button>
          </form>

          <div className="mt-5 space-y-6">
            {GROUPS.map(({ title, match }) => {
              const items = todos.filter(match);
              return (
                <Fragment key={title}>
                  {/* Under the working lists, above the finished ones, which only grow. */}
                  {title === FINISHED && offerHome && (
                    <section className={`rounded-xl border px-4 py-3 ${PROJECTS_TINT}`}>
                      <h3 className="font-heading font-semibold text-charcoal">Outgrowing a list?</h3>
                      <p className="mt-0.5 text-sm text-muted">
                        Give this project a board, files and messages. Your to-dos stay here.
                      </p>
                      <button
                        type="button"
                        disabled={givingHome}
                        onClick={() => void giveHome()}
                        className="mt-3 inline-flex items-center gap-2 rounded-lg bg-teal-700 px-3 py-1.5 text-sm font-heading font-semibold text-white hover:bg-teal-800 disabled:opacity-40"
                      >
                        <Logo app="projects" className="h-5 w-5" />
                        Give it a home in Projects GTD
                      </button>
                      {homeError && (
                        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
                          {homeError}
                        </p>
                      )}
                    </section>
                  )}
                  {items.length > 0 && (
                    <section>
                      <h3 className="mb-2 text-xs font-heading font-bold uppercase tracking-wide text-muted">
                        {title}
                      </h3>
                      <div className="space-y-2">
                        {items.map((t) => (
                          <TodoRow
                            key={t.id}
                            todo={t}
                            onToggleDone={toggleDone}
                            onToggleStar={toggleStar}
                            onEdit={setEditTodo}
                          />
                        ))}
                      </div>
                    </section>
                  )}
                </Fragment>
              );
            })}
          </div>
        </>
      )}
      {editTodo && (
        <TodoEditSheet
          todo={editTodo}
          projects={projects}
          contexts={filters?.contexts ?? []}
          onClose={() => setEditTodo(null)}
          onSaved={after}
        />
      )}
    </TodoShell>
  );
}
