import { useEffect, useMemo, useRef, useState } from 'react';
import { SearchFilterBar } from '../../shared/search';
import { apiErrorMessage } from '../../core/api/client';
import { createProject, listProjects, listTodos } from './api';
import { ProjectCard } from './components/ProjectCard';
import { PROJECT_STATUSES } from './constants';
import { useAppHref } from './hop';
import { updateProjectStatus } from './projectActions';
import { linkShown, useProjectLinks } from './projectLinks';
import { EmptyState, FilterEmptyState, LoadFailed, LoadingRows, TodoShell } from './TodoShell';
import type { TodoProject, TodoProjectStatus } from './types';
import { refreshMeta, useListFilters } from './useTodoMeta';

const inputCls =
  'w-full rounded-lg border border-line bg-cream px-3 py-2 text-base sm:text-sm text-charcoal focus:border-brand focus:outline-none';

const NO_PROJECTS: TodoProject[] = [];

/** Projects = outcomes needing more than one action. GTD: every ACTIVE
 * project should have at least one next action — the card warns when not. */
export function ProjectsPage() {
  const [status, setStatus] = useState<TodoProjectStatus>('active');
  const [projects, setProjects] = useState<TodoProject[] | null>(null);
  const [projectsWithNext, setProjectsWithNext] = useState<Set<number>>(new Set());
  const [failed, setFailed] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [areaSel, setAreaSel] = useState('');
  const areas = useListFilters()?.areas ?? [];
  const [formError, setFormError] = useState('');
  const [search, setSearch] = useState('');
  const projectsGtd = useAppHref('projects');
  // The projects that have a home in Projects GTD carry a chip.
  const { links } = useProjectLinks();
  const linkOf = useMemo(() => new Map((links ?? []).map((l) => [l.project_id, l])), [links]);

  // Only the latest load for the tab now showing may land. `shown` covers a caller
  // holding a tab the user has since left (a create or close-out that awaited its
  // write); `loadSeq` covers a slow answer overtaken by a newer request.
  const shown = useRef(status);
  const loadSeq = useRef(0);
  const load = (requested: TodoProjectStatus) => {
    const s = requested === shown.current ? requested : shown.current;
    const seq = ++loadSeq.current;
    // Next actions ride along so the stalled warning measures the GTD thing
    // ("no next action"), not open_count — someday/waiting items keep
    // open_count > 0 on a project that is still stalled. Deferred next actions
    // count: a project whose next step is scheduled to come back is not stalled.
    Promise.all([listProjects(s), listTodos({ status: 'next_action', limit: 500, include_deferred: true })])
      .then(([p, next]) => {
        if (seq !== loadSeq.current) return;
        setProjects(p);
        // `next` is every next action, however many (`listTodos` pages), so a
        // project missing from it has none.
        setProjectsWithNext(new Set(next.map((t) => t.project_id).filter((id): id is number => id !== null)));
        setFailed(false);
      })
      .catch(() => {
        if (seq === loadSeq.current) setFailed(true);
      });
  };
  useEffect(() => {
    shown.current = status;
    load(status);
  }, [status]);

  const add = async () => {
    if (!name.trim()) return;
    setFormError('');
    try {
      await createProject({ name: name.trim(), notes, area_id: areaSel ? Number(areaSel) : null });
      setName('');
      setNotes('');
      setAreaSel('');
      setShowForm(false);
      load(status);
      void refreshMeta();
    } catch (e) {
      setFormError(apiErrorMessage(e, 'Create failed'));
    }
  };

  const closeOut = async (e: React.MouseEvent, p: TodoProject) => {
    // The card is a Link; the button must not navigate.
    e.preventDefault();
    e.stopPropagation();
    const reopening = p.status === 'completed' || p.status === 'dropped';
    if (await updateProjectStatus(p.id, reopening ? 'active' : 'completed')) {
      load(status);
      void refreshMeta();
    }
  };

  const items = projects ?? NO_PROJECTS;
  // Name + notes — a plain substring match.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? items.filter((p) => `${p.name}\n${p.notes}`.toLowerCase().includes(q)) : items;
  }, [items, search]);

  return (
    <TodoShell active="projects">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex gap-1 overflow-x-auto no-scrollbar border-b border-line-faint">
          {PROJECT_STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`whitespace-nowrap px-3 py-2 text-sm capitalize transition-colors border-b-2 -mb-px ${
                status === s
                  ? 'text-charcoal font-semibold border-brand'
                  : 'text-muted font-medium border-transparent hover:text-charcoal'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="shrink-0 rounded-lg bg-brand-dark px-3 py-1.5 text-sm font-heading text-white hover:bg-brand-deep"
        >
          New project
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void add();
          }}
          className="mb-4 space-y-2 rounded-xl border border-line bg-cream p-4"
        >
          <input
            className={inputCls}
            placeholder="Project name (the outcome)"
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
          <textarea
            className={`${inputCls} min-h-16`}
            placeholder="Desired outcome, background, links"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          {areas.length > 0 && (
            <select className={inputCls} value={areaSel} aria-label="Area" onChange={(e) => setAreaSel(e.target.value)}>
              <option value="">No area</option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
          {formError && <p className="text-sm text-brand-ink">{formError}</p>}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!name.trim()}
              className="rounded-lg bg-brand-dark px-4 py-2 text-sm font-heading text-white hover:bg-brand-deep disabled:opacity-40"
            >
              Create
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-lg border border-line px-4 py-2 text-sm font-heading text-charcoal hover:bg-sand"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {failed && <LoadFailed retry={() => load(status)} />}
      {!failed && projects === null && <LoadingRows />}
      {!failed && projects !== null && (
        <>
          <SearchFilterBar
            query={search}
            onQueryChange={setSearch}
            placeholder="Search projects…"
            visibleCount={visible.length}
            totalCount={items.length}
            countNoun="project"
            active={search.trim() !== ''}
            activeFacetCount={0}
            onClear={() => setSearch('')}
          />
          {items.length === 0 && (
            <EmptyState
              title={`No ${status} projects`}
              hint="A project is any outcome that needs more than one action."
            />
          )}
          {items.length > 0 && visible.length === 0 && <FilterEmptyState />}
          <div className="grid gap-3 sm:grid-cols-2">
            {visible.map((p) => (
              <ProjectCard
                key={p.id}
                project={p}
                board={linkShown(linkOf.get(p.id), p.status)}
                stalled={status === 'active' && !projectsWithNext.has(p.id)}
                onCloseOut={closeOut}
              />
            ))}
          </div>
        </>
      )}
      {projectsGtd && (
        <p className="mt-6 text-sm text-muted">
          A project here is an outcome that takes a few next actions. Work that needs files, research and other people
          has a home in{' '}
          <a href={projectsGtd} className="underline hover:text-charcoal">
            Projects GTD
          </a>
          .
        </p>
      )}
    </TodoShell>
  );
}
