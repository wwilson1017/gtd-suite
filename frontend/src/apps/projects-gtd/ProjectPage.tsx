// Projects GTD — a project's Overview tab, showing the project home: who's in it
// and the ••• menu on top, its description, dates and status, the latest activity,
// then a card for each tool with a live preview, and the dashed "+" that adds one.
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { getActivity, getMuted, getProject, setBookmark, setDock, setMuted, updateBoard } from './api';
import { DatesEditor, scheduleText } from './CheckinsPage';
import { Hill } from './HillChart';
import { ActivityLine, NewProject } from './HomePage';
import { NeedleBox } from './Needle';
import { ProjectsShell } from './ProjectsShell';
import type { ActivityEvent, DockEntry, Project, Tool } from './types';
import { Avatar, AvatarStack, Crumbs, day, Menu, Perma, plain, ProgressPie, TOOL_PATH, ToolHeading, when } from './ui';

const TOOL_BLURB: Record<Tool, string> = {
  message_board: 'Post announcements, pitch ideas, and gather feedback, with each discussion kept on its own page.',
  todoset: 'Make lists of work that needs doing, assign it, set due dates, and check it off.',
  vault: 'Write documents and keep links to files, in folders, all in one place.',
  chat: 'Quick talk for the project, with your AI tools in the room too.',
  doors: 'Links out to the tools this project uses elsewhere: a design file, a drive, a repo.',
  schedule: 'Put events and deadlines on a calendar; due to-dos and cards show up on it too.',
  questionnaire: 'Ask a question on a schedule, of you and your AI tools, and read the answers day by day.',
  kanban_board: 'Move cards across columns: triage what comes in, track what is in progress, see what is done.',
};

function MessagePreview({ project }: { project: Project }) {
  const [first, ...rest] = project.previews.message_board ?? [];
  if (!first) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.message_board}</p>;
  return (
    <div>
      <div className="flex gap-3">
        <Avatar person={first.creator} size={36} />
        <div className="min-w-0">
          <p className="text-[13px] text-bc-subtle">
            {first.creator?.name} • {when(first.created_at)}
          </p>
          <p className="font-bold leading-snug">
            {first.category && <span className="mr-1">{first.category.split(' ')[0]}</span>}
            {first.title}
          </p>
          {first.body && <p className="line-clamp-3 text-[14px] text-bc-subtle">{plain(first.body)}</p>}
        </div>
      </div>
      {rest.length > 0 && (
        <ul className="mt-3 space-y-2 border-t border-bc-line pt-3">
          {rest.map((m) => (
            <li key={m.id} className="flex items-center gap-2 text-[14px]">
              <Avatar person={m.creator} size={20} />
              <span className="truncate font-semibold">{m.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TodoPreview({ project }: { project: Project }) {
  const lists = project.previews.todoset ?? [];
  const hill = project.previews.hill ?? [];
  if (!lists.length) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.todoset}</p>;
  return (
    <>
      {hill.length > 0 && <Hill lists={hill} small />}
      <ul className="space-y-2">
        {lists.map((l) => (
          <li key={l.id} className="flex items-center gap-2">
            <ProgressPie done={l.completed_count ?? 0} total={l.todos_count ?? 0} size={18} />
            <span className="truncate font-semibold">{l.title}</span>
            <span className="ml-auto shrink-0 text-[13px] text-bc-subtle">
              {l.completed_count}/{l.todos_count}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function CardPreview({ project }: { project: Project }) {
  const columns = project.previews.kanban_board ?? [];
  if (!columns.length) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.kanban_board}</p>;
  return (
    <div className="flex gap-1.5 overflow-hidden">
      {columns.map((c, i) => (
        <div
          key={c.id}
          className="flex min-h-28 min-w-0 flex-1 flex-col items-center rounded-sm border-t-4 bg-bc-wash px-1 pt-2"
          style={{ borderTopColor: ['#ae80ff', '#f58e02', '#ef63b8', '#42a3ff', '#56b66f', '#0db3c1'][i % 6] }}
        >
          <span className="text-[12px] font-bold text-bc-subtle">({c.cards})</span>
          <span className="mt-1 text-[11px] font-semibold uppercase tracking-wider text-bc-subtle [writing-mode:vertical-rl]">
            {c.name}
          </span>
        </div>
      ))}
    </div>
  );
}

const DOC_ICON: Record<string, string> = { vault: '📁', document: '📄', link: '🔗' };

function DocsPreview({ project }: { project: Project }) {
  const items = project.previews.vault ?? [];
  if (!items.length) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.vault}</p>;
  return (
    <div className="grid grid-cols-3 gap-2">
      {items.slice(0, 6).map((i) => (
        <div key={i.id} className={`bc-c-${i.color} flex min-w-0 flex-col items-center text-center`}>
          <span aria-hidden className="text-3xl">
            {DOC_ICON[i.type]}
          </span>
          <span className="line-clamp-2 text-[12px] font-semibold">{i.title}</span>
        </div>
      ))}
    </div>
  );
}

function SchedulePreview({ project }: { project: Project }) {
  const range = project.previews.schedule;
  const rows = [
    ...(range?.events ?? []).map((e) => ({ key: `e${e.id}-${e.on}`, on: e.on, title: e.title, due: false })),
    ...(range?.due ?? []).map((d) => ({ key: `d${d.kind}${d.id}`, on: d.on, title: d.title, due: true })),
  ]
    .sort((a, b) => a.on.localeCompare(b.on))
    .slice(0, 5);
  if (!rows.length) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.schedule}</p>;
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.key} className="flex items-baseline gap-2 text-[14px]">
          <span className="w-24 shrink-0 whitespace-nowrap text-[12px] font-bold uppercase text-bc-subtle">
            {day(r.on)}
          </span>
          <span className="truncate font-semibold">{r.due ? `Due: ${r.title}` : r.title}</span>
        </li>
      ))}
    </ul>
  );
}

function CheckinsPreview({ project }: { project: Project }) {
  const questions = project.previews.questionnaire ?? [];
  if (!questions.length) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.questionnaire}</p>;
  return (
    <ul className="space-y-2">
      {questions.map((q) => (
        <li key={q.id}>
          <span className="block truncate font-semibold">{q.title}</span>
          <span className="block truncate text-[12px] text-bc-subtle">{scheduleText(q)}</span>
        </li>
      ))}
    </ul>
  );
}

function ChatPreview({ project }: { project: Project }) {
  const lines = project.previews.chat ?? [];
  if (!lines.length) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.chat}</p>;
  return (
    <ul className="space-y-2">
      {lines.map((l) => (
        <li key={l.id} className="flex gap-2 text-[14px]">
          <Avatar person={l.creator} size={22} />
          <span className="min-w-0">
            <b>{l.creator?.name}</b> <span className="line-clamp-2">{plain(l.body)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function DoorsPreview({ project }: { project: Project }) {
  const doors = project.previews.doors ?? [];
  if (!doors.length) return <p className="text-[15px] text-bc-subtle">{TOOL_BLURB.doors}</p>;
  return (
    <ul className="space-y-1.5">
      {doors.slice(0, 6).map((d) => (
        <li key={d.id} className="truncate text-[14px] font-semibold">
          🚪 {d.title}
        </li>
      ))}
    </ul>
  );
}

const PREVIEW: Record<Tool, (p: { project: Project }) => React.JSX.Element> = {
  message_board: MessagePreview,
  todoset: TodoPreview,
  vault: DocsPreview,
  chat: ChatPreview,
  doors: DoorsPreview,
  schedule: SchedulePreview,
  questionnaire: CheckinsPreview,
  kanban_board: CardPreview,
};

/** The project's tools: on or off, renamed, in order (••• → Change tools, and the + tile). */
function ToolsEditor({
  dock,
  onSave,
  onClose,
}: {
  dock: DockEntry[];
  onSave: (d: DockEntry[]) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(dock);
  const [error, setError] = useState('');
  const set = (i: number, patch: Partial<DockEntry>) =>
    setDraft((d) => d.map((t, n) => (n === i ? { ...t, ...patch } : t)));
  const swap = (i: number, j: number) =>
    setDraft((d) => {
      if (j < 0 || j >= d.length) return d;
      const next = [...d];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  return (
    <div role="dialog" aria-label="Change tools" className="mt-4 rounded-lg border border-bc-line bg-bc-wash p-4">
      <h2 className="text-lg font-bold">Change tools</h2>
      <p className="text-sm text-bc-subtle">
        Turn tools on or off, rename them and put them in order. Turning one off keeps what's in it.
      </p>
      <ul className="mt-3 space-y-2">
        {draft.map((t, i) => (
          <li key={t.tool} className="flex flex-wrap items-center gap-2 rounded-lg bg-bc-canvas p-2">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                className="bc-checkbox"
                checked={t.enabled}
                onChange={(e) => set(i, { enabled: e.target.checked })}
              />
              <span className="sr-only">On</span>
            </label>
            <input
              value={t.title}
              onChange={(e) => set(i, { title: e.target.value })}
              aria-label="Tool name"
              maxLength={100}
              className="bc-input max-w-60 flex-1 py-1"
            />
            <span className="ml-auto flex gap-1">
              <button type="button" className="bc-btn bc-btn-sm" aria-label="Move up" onClick={() => swap(i, i - 1)}>
                ↑
              </button>
              <button type="button" className="bc-btn bc-btn-sm" aria-label="Move down" onClick={() => swap(i, i + 1)}>
                ↓
              </button>
            </span>
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="mt-2 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="bc-btn bc-btn-primary"
          onClick={() => void onSave(draft).catch((e) => setError(apiErrorMessage(e, 'Could not save the tools.')))}
        >
          Save changes
        </button>
        <button type="button" className="bc-btn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function AddTool({ dock, onAdd }: { dock: DockEntry[]; onAdd: (tool: Tool) => void }) {
  const [open, setOpen] = useState(false);
  const off = dock.filter((t) => !t.enabled);
  if (!off.length) return null;
  return (
    <div>
      {open ? (
        <div className="rounded-lg border-2 border-dashed border-bc-line p-3">
          <p className="font-bold">Add a tool</p>
          <ul className="mt-2 space-y-2">
            {off.map((t) => (
              <li key={t.tool}>
                <button
                  type="button"
                  onClick={() => onAdd(t.tool)}
                  className="w-full rounded-lg border border-bc-line bg-bc-canvas p-3 text-left hover:border-bc-faint"
                >
                  <span className="block font-bold text-bc-heading">{t.title}</span>
                  <span className="block text-[14px] text-bc-subtle">{TOOL_BLURB[t.tool]}</span>
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="mt-2 text-sm text-bc-subtle underline" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          aria-label="Add a tool"
          onClick={() => setOpen(true)}
          className="flex h-20 w-20 items-center justify-center rounded-lg border-2 border-dashed border-bc-line text-4xl font-light text-bc-faint hover:border-bc-faint hover:text-bc-ink"
        >
          +
        </button>
      )}
    </div>
  );
}

export function ProjectPage() {
  const id = Number(useParams().id);
  const [project, setProject] = useState<Project | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [editing, setEditing] = useState(false);
  const [quietHere, setQuietHere] = useState(false); // the project's bell: "Don't notify me"
  useEffect(() => {
    getMuted({ project_id: id }).then(setQuietHere, () => {});
  }, [id]);
  const [tools, setTools] = useState(false);
  const [dates, setDates] = useState(false);
  const [using, setUsing] = useState(false);
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const load = useCallback(() => {
    getProject(id).then(
      (p) => {
        setProject(p);
        setName(p.name);
        setNotes(p.notes);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load this project.')),
    );
    getActivity({ project_id: id }).then(
      (r) => setActivity(r.events.slice(0, 5)),
      () => {},
    );
  }, [id]);
  useEffect(load, [load]);

  if (error)
    return (
      <ProjectsShell>
        <Perma>
          <p role="alert" className="text-bc-unread">
            {error}
          </p>
        </Perma>
      </ProjectsShell>
    );
  if (!project)
    return (
      <ProjectsShell>
        <Perma>
          <p className="text-bc-subtle">Loading…</p>
        </Perma>
      </ProjectsShell>
    );

  const saveDock = async (dock: DockEntry[]) => {
    await setDock(id, dock);
    setTools(false);
    load();
  };
  const addTool = (tool: Tool) =>
    void saveDock(project.dock.map((t) => (t.tool === tool ? { ...t, enabled: true } : t)));
  const saveInfo = async () => {
    try {
      await updateBoard(id, { name: name.trim(), notes: notes.trim() });
      setEditing(false);
      load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save the project.'));
    }
  };
  const on = project.dock.filter((t) => t.enabled);

  return (
    <ProjectsShell project={project} title={project.name}>
      <Perma>
        <Crumbs
          project={project}
          crumbs={[{ label: 'Home', to: '/' }]}
          right={
            <>
              {project.people.length > 0 && <AvatarStack people={project.people} size={28} />}
              <button
                type="button"
                className="bc-btn bc-btn-sm"
                onClick={() => void setBookmark({ project_id: id }, !project.bookmarked).then(load)}
              >
                🔖 {project.bookmarked ? 'Bookmarked' : 'Bookmark'}
              </button>
              <Menu
                items={[
                  { label: 'Edit name and description', onClick: () => setEditing(true) },
                  { label: 'Change tools', onClick: () => setTools(true) },
                  { label: 'Set the project dates', onClick: () => setDates(true) },
                  { label: 'Archived and trashed items', onClick: () => navigate(`/p/${id}/archive`) },
                  {
                    label: project.template ? 'Stop using it as a template' : 'Save as a template',
                    onClick: () => void updateBoard(id, { template: !project.template }).then(load),
                  },
                  {
                    label: project.pinned ? 'Unstar' : 'Star (pin to the top of Home)',
                    onClick: () => void updateBoard(id, { pinned: !project.pinned }).then(load),
                  },
                  {
                    label: project.folder ? `Move out of “${project.folder}”…` : 'Put in a folder on Home…',
                    onClick: () => {
                      const name = prompt(
                        'The Home folder to keep this project in (leave it empty for none):',
                        project.folder ?? '',
                      );
                      if (name !== null) void updateBoard(id, { folder: name.trim() }).then(load);
                    },
                  },
                  {
                    label: quietHere
                      ? '🔔 Notify me about this project again'
                      : "🔕 Don't notify me about this project",
                    onClick: () => void setMuted({ project_id: id }, !quietHere).then((r) => setQuietHere(r.muted)),
                  },
                  'sep',
                  project.status === 'active'
                    ? {
                        label: 'Archive this project',
                        onClick: () => {
                          if (confirm('Archive this project? It leaves Home; you can restore it.'))
                            void updateBoard(id, { status: 'archived' }).then(() => navigate('/'));
                        },
                      }
                    : {
                        label: 'Restore this project',
                        onClick: () => void updateBoard(id, { status: 'active' }).then(load),
                      },
                ]}
              />
            </>
          }
        />

        {!!project.template && (
          <div className="mb-4 rounded-lg bg-bc-highlight px-4 py-3 text-[15px]">
            <p>
              <b>This is a template.</b> New projects can start from it: its tools, lists, documents, events and cards,
              with everything re-opened and the dates moved to the new start. Its own dates and to-dos stay out of
              Reports and the Calendar.
              <button
                type="button"
                className="bc-btn bc-btn-primary bc-btn-sm ml-2"
                onClick={() => setUsing((u) => !u)}
              >
                Use this template
              </button>
            </p>
            {using && (
              <div className="mt-3">
                <NewProject template={id} onCancel={() => setUsing(false)} />
              </div>
            )}
          </div>
        )}

        {project.status === 'archived' && (
          <p className="mb-4 rounded-lg bg-bc-today px-4 py-2 text-[15px]">
            This project is archived. Restore it from the ••• menu to work in it.
          </p>
        )}

        {editing ? (
          <form
            className="max-w-2xl"
            onSubmit={(e) => {
              e.preventDefault();
              void saveInfo();
            }}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-label="Project name"
              maxLength={200}
              className="bc-input bc-title text-2xl"
            />
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              aria-label="Description"
              maxLength={20000}
              placeholder="Add a description"
              rows={2}
              className="bc-input mt-2"
            />
            <div className="mt-2 flex gap-2">
              <button type="submit" className="bc-btn bc-btn-primary" disabled={!name.trim()}>
                Save changes
              </button>
              <button type="button" className="bc-btn" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <header>
            <p className="flex items-start gap-2 text-[16px] text-bc-subtle">
              <span className="min-w-0 flex-1">
                {project.notes || (
                  <button type="button" className="hover:underline" onClick={() => setEditing(true)}>
                    Add a description
                  </button>
                )}
              </span>
              <button
                type="button"
                aria-label={project.pinned ? 'Unstar' : 'Star'}
                aria-pressed={!!project.pinned}
                onClick={() => void updateBoard(id, { pinned: !project.pinned }).then(load)}
                className={`text-2xl leading-none ${project.pinned ? 'text-[#e9b60f]' : 'text-bc-line hover:text-bc-faint'}`}
              >
                ★
              </button>
            </p>
            {(project.starts_on || project.ends_on) && !dates && (
              <p className="mt-1 text-[14px] text-bc-subtle">
                <button type="button" className="hover:underline" onClick={() => setDates(true)}>
                  {project.starts_on ? day(project.starts_on) : '…'} – {project.ends_on ? day(project.ends_on) : '…'}
                </button>
              </p>
            )}
          </header>
        )}
        {dates && (
          <DatesEditor
            project={project}
            onDone={() => {
              setDates(false);
              load();
            }}
          />
        )}
        {project.status === 'active' && <NeedleBox projectId={id} latest={project.needle} onMoved={load} />}

        {tools && <ToolsEditor dock={project.dock} onSave={saveDock} onClose={() => setTools(false)} />}

        {project.spotlight.length > 0 && (
          <section aria-label="Spotlight" className="mt-6">
            <h2 className="text-[13px] font-bold uppercase tracking-wider text-bc-subtle">✦ Spotlight</h2>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {project.spotlight.map((i) => (
                <Link
                  key={i.id}
                  to={`/i/${i.id}`}
                  className="rounded-lg border border-bc-line bg-bc-canvas px-4 py-3 hover:border-bc-faint"
                >
                  <span className="block font-bold">{i.title}</span>
                  <span className="block truncate text-[14px] text-bc-subtle">
                    {plain(i.body ?? '') || i.type.replace('_', ' ')}
                  </span>
                </Link>
              ))}
            </div>
          </section>
        )}

        {activity.length > 0 && (
          <section aria-label="Latest activity" className="mt-6 rounded-xl bg-bc-wash px-4 py-3">
            <h2 className="text-[13px] font-bold uppercase tracking-wider text-bc-subtle">Latest activity</h2>
            <ul className="mt-2 space-y-2">
              {activity.map((e) => (
                <li key={e.id}>
                  <ActivityLine e={e} showProject={false} />
                </li>
              ))}
            </ul>
          </section>
        )}

        {on.every((t) => t.tool === 'kanban_board') && (
          <div className="mt-8 max-w-xl">
            <p className="text-lg font-bold">Just the board, for now.</p>
            <p className="text-bc-subtle">
              Add the ones it needs: Messages to talk, To-dos for the work, Docs, Chat, a Calendar, Check-ins, Links.
            </p>
          </div>
        )}

        <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {on.map((t) => {
            const Preview = PREVIEW[t.tool];
            return (
              <Link
                key={t.tool}
                aria-label={t.title}
                to={t.tool === 'kanban_board' ? `/p/${id}` : `/p/${id}/${TOOL_PATH[t.tool]}`}
                className="block min-h-40 rounded-xl border border-bc-line bg-bc-canvas p-4 hover:border-bc-faint"
              >
                <ToolHeading>{t.title}</ToolHeading>
                <div className="mt-3">
                  <Preview project={project} />
                </div>
              </Link>
            );
          })}
        </div>
        {project.status === 'active' && (
          <div className="mt-6">
            <AddTool dock={project.dock} onAdd={addTool} />
          </div>
        )}
      </Perma>
    </ProjectsShell>
  );
}
