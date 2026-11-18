// Projects GTD — Home, as Trello's boards page: every project a coloured tile
// (starred first, then each Home folder), a tile to make a new one, and your
// assignments and the latest activity down the right.
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { createBoard, getHome, getTemplates, listBoards, startFromTemplate, updateBoard } from './api';
import { ProjectsShell } from './ProjectsShell';
import { ownProjectMade, useSamplesOnHome } from './SampleData';
import type { ActivityEvent, BoardSummary, Home, HomeProject } from './types';
import { Avatar, AvatarStack, day, itemPath, when } from './ui';

/** Trello's board colours: each project keeps one, by its id. */
const TILE_COLORS = ['#0079bf', '#d29034', '#519839', '#b04632', '#89609e', '#cd5a91', '#4bbf6b', '#00aecc', '#838c91'];
export const tileColor = (id: number) => TILE_COLORS[id % TILE_COLORS.length];

function Star({ on, onToggle, label }: { on: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={on ? `Unstar ${label}` : `Star ${label}`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
      className={`text-xl leading-none ${on ? 'text-[#f5cd47]' : 'text-white/50 hover:text-white'}`}
    >
      ★
    </button>
  );
}

function ProjectCard({ project, onStar }: { project: HomeProject; onStar: () => void }) {
  return (
    <Link
      to={`/p/${project.id}`}
      style={{ background: tileColor(project.id) }}
      className="group flex min-h-28 flex-col rounded-xl p-3 text-white shadow-sm hover:brightness-95"
    >
      <div className="flex items-start gap-2">
        <h3 className="min-w-0 flex-1 text-[17px] font-bold leading-tight">{project.name}</h3>
        <Star on={!!project.pinned} onToggle={onStar} label={project.name} />
      </div>
      {project.sample && (
        <span className="mt-1 self-start rounded bg-white px-1.5 py-0.5 text-[11px] font-extrabold tracking-wider text-neutral-900">
          SAMPLE
        </span>
      )}
      {project.notes && <p className="mt-1 line-clamp-2 text-[13px] text-white/85">{project.notes}</p>}
      <div className="mt-auto flex items-center gap-2 pt-2 text-[12px] text-white/85">
        <span>
          {project.cards} card{project.cards === 1 ? '' : 's'}
        </span>
        {project.people.length > 0 && (
          <span className="ml-auto">
            <AvatarStack people={project.people} size={22} max={5} />
          </span>
        )}
      </div>
    </Link>
  );
}

/** One line of the activity timeline: who did what to which thing, in which project. */
export function ActivityLine({ e, showProject = true }: { e: ActivityEvent; showProject?: boolean }) {
  const title = e.recording_title || e.card_title || e.board_name;
  return (
    <div className="flex gap-2.5">
      <Avatar person={e.creator} size={28} />
      <p className="min-w-0 text-[15px] leading-snug">
        <span className="font-bold">{e.creator?.name ?? 'Someone'}</span> {e.verb}{' '}
        {e.action !== 'started' && (
          <Link to={itemPath(e.card_board_id ?? e.board_id, e)} className="text-bc-blue underline">
            {title}
          </Link>
        )}
        {e.action === 'moved' && e.detail && <> to {e.detail}</>}
        {e.action === 'boosted' && e.detail && <> with {e.detail}</>}
        {e.action === 'chatted' && e.detail && <span className="text-bc-subtle">: “{e.detail}”</span>}
        {showProject && e.action !== 'started' && <span className="text-bc-subtle"> — {e.board_name}</span>}
        {e.action === 'started' && (
          <Link to={`/p/${e.board_id}`} className="text-bc-blue underline">
            {' '}
            {e.board_name}
          </Link>
        )}
        {e.action === 'commented' && e.detail && <span className="mt-0.5 block text-bc-subtle">“{e.detail}”</span>}
        <span className="block text-[13px] text-bc-faint">{when(e.created_at)}</span>
      </p>
    </div>
  );
}

export function NewProject({ onCancel, template: chosen }: { onCancel: () => void; template?: number }) {
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [templates, setTemplates] = useState<{ id: number; name: string }[]>([]);
  const [template, setTemplate] = useState(chosen ? String(chosen) : '');
  const [starts, setStarts] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  useEffect(() => {
    getTemplates().then(setTemplates, () => {});
  }, []);
  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      // A new project is a board and nothing else; its Overview adds the other tools.
      // From a template it starts with the template's tools and everything in them.
      const board = template
        ? await startFromTemplate(Number(template), name.trim(), starts || undefined)
        : await createBoard(name.trim(), notes.trim(), ['kanban_board']);
      ownProjectMade();
      navigate(`/p/${board.id}`);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not make the project.'));
      setBusy(false);
    }
  };
  return (
    <form
      className="rounded-lg border border-bc-line bg-bc-canvas p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void create();
      }}
    >
      <label className="block text-sm font-semibold" htmlFor="np-name">
        Name this project
      </label>
      <input
        id="np-name"
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={200}
        placeholder="e.g. Kitchen remodel"
        className="bc-input mt-1"
      />
      {templates.length > 0 && (
        <>
          <label className="mt-3 block text-sm font-semibold" htmlFor="np-template">
            Start from
          </label>
          <select
            id="np-template"
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            className="bc-input mt-1"
          >
            <option value="">A blank project</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                The “{t.name}” template
              </option>
            ))}
          </select>
        </>
      )}
      {template ? (
        <>
          <label className="mt-3 block text-sm font-semibold" htmlFor="np-starts">
            It starts on (optional: every date in it moves with it)
          </label>
          <input
            id="np-starts"
            type="date"
            value={starts}
            onChange={(e) => setStarts(e.target.value)}
            className="bc-input mt-1 w-auto"
          />
        </>
      ) : (
        <>
          <label className="mt-3 block text-sm font-semibold" htmlFor="np-notes">
            Add a description (optional)
          </label>
          <input
            id="np-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
            placeholder="What's it for?"
            className="bc-input mt-1"
          />
        </>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button type="submit" className="bc-btn bc-btn-primary" disabled={!name.trim() || busy}>
          Make this project
        </button>
        <button type="button" className="bc-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Basecamp 5's Home folders: the top (key ''): starred projects, wherever they are filed,
 * and those in no folder; then each folder by name. Order within each is kept. */
export function byFolder<P extends { folder?: string; pinned?: number | boolean }>(projects: P[]): Map<string, P[]> {
  const home = (p: P) => (p.pinned ? '' : (p.folder ?? ''));
  const out = new Map<string, P[]>([['', []]]);
  const names = [...new Set(projects.map(home).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  for (const name of names) out.set(name, []);
  for (const p of projects) out.get(home(p))!.push(p);
  return out;
}

export function HomePage() {
  const [home, setHome] = useState<Home | null>(null);
  const [filter, setFilter] = useState('');
  const [making, setMaking] = useState<boolean | number>(false);
  const [archived, setArchived] = useState<BoardSummary[] | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    getHome().then(setHome, (e) => setError(apiErrorMessage(e, 'Could not load Home.')));
  }, []);
  useEffect(load, [load]);
  useSamplesOnHome(home ? home.projects.length : null, load);

  const star = async (p: HomeProject) => {
    await updateBoard(p.id, { pinned: !p.pinned });
    load();
  };
  const live = home?.projects.filter((p) => !p.template) ?? [];
  const templates = home?.projects.filter((p) => p.template) ?? [];
  const shown = live.filter((p) => p.name.toLowerCase().includes(filter.trim().toLowerCase()));
  const folders = byFolder(shown);

  const tiles = (projects: HomeProject[], adding = false) => (
    <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
      {projects.map((p) => (
        <ProjectCard key={p.id} project={p} onStar={() => void star(p)} />
      ))}
      {adding && making === false && (
        <button
          type="button"
          onClick={() => setMaking(true)}
          className="flex min-h-28 items-center justify-center rounded-xl bg-bc-wash text-[15px] text-bc-subtle hover:bg-bc-line hover:text-bc-ink"
        >
          + New project
        </button>
      )}
    </div>
  );
  const starred = (folders.get('') ?? []).filter((p) => p.pinned);
  const loose = (folders.get('') ?? []).filter((p) => !p.pinned);

  return (
    <ProjectsShell>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section aria-label="Projects" className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="mr-auto text-2xl font-bold">Projects</h1>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Find a project…"
              aria-label="Find a project"
              className="bc-input w-56 py-1.5 text-[14px]"
            />
            <button type="button" className="bc-btn bc-btn-primary bc-btn-sm" onClick={() => setMaking(true)}>
              + New project
            </button>
          </div>
          {making !== false && (
            <div className="mt-4 max-w-xl">
              <NewProject
                key={String(making)}
                onCancel={() => setMaking(false)}
                template={typeof making === 'number' ? making : undefined}
              />
            </div>
          )}
          {error && (
            <p role="alert" className="mt-3 text-bc-unread">
              {error}
            </p>
          )}
          {home && live.length === 0 && making === false && (
            <div className="mt-6 rounded-xl border border-dashed border-bc-faint bg-bc-canvas p-6 text-center">
              <p className="text-lg font-bold">Make your first project.</p>
              <p className="mt-1 text-bc-subtle">
                A project is a board of cards you move from column to column, with messages, to-dos and docs beside it
                when it needs them. Your AI tools work in it with you.
              </p>
              <button type="button" className="bc-btn bc-btn-primary mt-4" onClick={() => setMaking(true)}>
                Make a new project
              </button>
            </div>
          )}
          {starred.length > 0 && (
            <div className="mt-6">
              <h2 className="text-[15px] font-bold">★ Starred</h2>
              {tiles(starred)}
            </div>
          )}
          {live.length > 0 && (
            <div className="mt-6">
              {starred.length > 0 && <h2 className="text-[15px] font-bold">Your projects</h2>}
              {tiles(loose, true)}
            </div>
          )}
          {[...folders]
            .filter(([name]) => name)
            .map(([name, projects]) => (
              <details key={name} open className="mt-6">
                <summary className="cursor-pointer text-[15px] font-bold">
                  📁 {name} <span className="font-normal text-bc-subtle">({projects.length})</span>
                </summary>
                {tiles(projects)}
              </details>
            ))}
          {templates.length > 0 && (
            <div className="mt-8">
              <h2 className="text-[15px] font-bold">Templates</h2>
              <ul className="mt-1 space-y-1">
                {templates.map((t) => (
                  <li key={t.id} className="flex items-center gap-3 text-sm">
                    <Link to={`/p/${t.id}`} className="underline">
                      {t.name}
                    </Link>
                    <button type="button" className="text-bc-blue underline" onClick={() => setMaking(t.id)}>
                      Use this template
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-8">
            {archived === null ? (
              <button
                type="button"
                className="text-sm text-bc-subtle underline"
                onClick={() => void listBoards('archived').then(setArchived)}
              >
                Archived projects
              </button>
            ) : (
              <div>
                <h2 className="text-sm font-bold">Archived projects</h2>
                {archived.length === 0 && <p className="text-sm text-bc-subtle">None.</p>}
                <ul className="mt-1 space-y-1">
                  {archived.map((b) => (
                    <li key={b.id} className="flex items-center gap-3 text-sm">
                      <Link to={`/p/${b.id}`} className="underline">
                        {b.name}
                      </Link>
                      <button
                        type="button"
                        className="text-bc-blue underline"
                        onClick={() =>
                          void updateBoard(b.id, { status: 'active' }).then(() => {
                            setArchived(null);
                            load();
                          })
                        }
                      >
                        Restore
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>

        <aside aria-label="Latest activity" className="min-w-0">
          {home && home.assignments.length > 0 && (
            <div className="mb-6">
              <h2 className="flex items-baseline justify-between text-[15px] font-bold">
                Your assignments{' '}
                <Link to="/my/tasks" className="text-sm font-normal text-bc-blue underline">
                  View all
                </Link>
              </h2>
              <ul className="mt-2 space-y-1.5">
                {home.assignments.slice(0, 6).map((t) => (
                  <li key={t.id} className="text-[15px]">
                    <Link to={`/i/${t.id}`} className="underline decoration-bc-line hover:decoration-bc-ink">
                      {t.title}
                    </Link>
                    <span className="text-bc-subtle">
                      {' '}
                      — {t.board_name}
                      {t.due_on ? `, due ${day(t.due_on)}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <h2 className="flex items-baseline justify-between text-[15px] font-bold">
            Latest activity{' '}
            <Link to="/activity" className="text-sm font-normal text-bc-blue underline">
              View all
            </Link>
          </h2>
          <ol className="mt-3 space-y-4 border-l border-bc-line pl-4">
            {home?.activity.map((e) => (
              <li key={e.id}>
                <ActivityLine e={e} />
              </li>
            ))}
            {home && home.activity.length === 0 && <li className="text-sm text-bc-subtle">Nothing yet.</li>}
          </ol>
        </aside>
      </div>
    </ProjectsShell>
  );
}
