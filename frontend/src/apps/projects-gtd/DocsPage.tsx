// Projects GTD — Docs & Files, as Basecamp 5 lays it out: one view of a folder
// (folders first, then documents and links), grid or list (remembered per
// folder in this browser), sorted by name, newest or last changed; "+ New"
// makes a folder, a Markdown document or a link to a file kept elsewhere.
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { createItem, getFolder, getProject, type Folder } from './api';
import { ProjectsShell } from './ProjectsShell';
import type { Item, Project } from './types';
import { ColorPicker, Crumbs, EmptyState, Menu, Perma, plain, when } from './ui';

const ICON: Record<string, string> = { vault: '📁', document: '📄', link: '🔗' };

function view(key: string): 'grid' | 'list' {
  try {
    return localStorage.getItem(key) === 'list' ? 'list' : 'grid';
  } catch {
    return 'grid';
  }
}

function Tile({ item, onOpen }: { item: Item; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`bc-c-${item.color} flex h-full flex-col items-center rounded-lg border border-bc-line bg-bc-canvas p-4 text-center hover:border-bc-faint`}
    >
      <span aria-hidden className="text-5xl" style={item.color ? { filter: 'drop-shadow(0 0 0 var(--c))' } : undefined}>
        {ICON[item.type]}
      </span>
      {item.color && <span className="mt-1 h-1 w-10 rounded" style={{ background: 'var(--c)' }} />}
      <span className="mt-2 line-clamp-2 font-bold">{item.title}</span>
      <span className="mt-1 text-[13px] text-bc-subtle">
        {item.type === 'vault'
          ? `${item.items_count ?? 0} item${item.items_count === 1 ? '' : 's'}`
          : `${item.creator?.name ?? ''} · ${when(item.updated_at)}`}
      </span>
    </button>
  );
}

function NewThing({
  kind,
  projectId,
  folderId,
  onDone,
}: {
  kind: 'vault' | 'document' | 'link';
  projectId: number;
  folderId: number | null;
  onDone: (made?: Item) => void;
}) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [url, setUrl] = useState('');
  const [color, setColor] = useState('');
  const [error, setError] = useState('');
  const save = async () => {
    try {
      const made = await createItem(
        projectId,
        kind,
        {
          title: title.trim(),
          ...(kind === 'document' ? { body } : {}),
          ...(kind === 'link' ? { url: url.trim(), body } : {}),
          ...(color ? { color } : {}),
        },
        folderId ? { parent_id: folderId } : {},
      );
      onDone(made);
    } catch (e) {
      setError(apiErrorMessage(e, 'That did not save.'));
    }
  };
  const label = { vault: 'folder', document: 'document', link: 'link' }[kind];
  return (
    <form
      className="mt-4 rounded-lg border border-bc-line p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <p className="font-bold">New {label}</p>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        placeholder={`Name this ${label}…`}
        aria-label="Title"
        maxLength={500}
        className="bc-input mt-2"
      />
      {kind === 'link' && (
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://docs.google.com/…"
          aria-label="Address"
          maxLength={500}
          className="bc-input mt-2"
        />
      )}
      {kind !== 'vault' && (
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={kind === 'document' ? 10 : 2}
          placeholder={kind === 'document' ? 'Write the document… (Markdown works)' : 'Notes (optional)'}
          aria-label="Body"
          maxLength={20000}
          className="bc-input mt-2 text-[16px]"
        />
      )}
      <div className="mt-2">
        <ColorPicker value={color} onChange={setColor} />
      </div>
      {error && (
        <p role="alert" className="mt-1 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          className="bc-btn bc-btn-primary"
          disabled={!title.trim() || (kind === 'link' && !url.trim())}
        >
          {kind === 'document' ? 'Save this document' : `Add this ${label}`}
        </button>
        <button type="button" className="bc-btn" onClick={() => onDone()}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function DocsPage() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const folderId = params.get('folder') ? Number(params.get('folder')) : null;
  const [project, setProject] = useState<Project | null>(null);
  const [folder, setFolder] = useState<Folder | null>(null);
  const [sort, setSort] = useState('name');
  const [making, setMaking] = useState<'' | 'vault' | 'document' | 'link'>('');
  const viewKey = `bc-docs-view-${id}-${folderId ?? 'top'}`;
  const [layout, setLayout] = useState(() => view(viewKey));
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const load = useCallback(() => {
    getFolder(id, folderId, sort).then(setFolder, (e) => setError(apiErrorMessage(e, 'Could not load this folder.')));
  }, [id, folderId, sort]);
  useEffect(load, [load]);
  useEffect(() => {
    getProject(id).then(setProject, () => {});
  }, [id]);
  const [previousViewKey, setPreviousViewKey] = useState(viewKey);
  if (viewKey !== previousViewKey) {
    setPreviousViewKey(viewKey);
    setLayout(view(viewKey));
  }
  const setView = (v: 'grid' | 'list') => {
    setLayout(v);
    try {
      localStorage.setItem(viewKey, v);
    } catch {
      /* fine */
    }
  };
  const open = (item: Item) =>
    item.type === 'vault' ? setParams({ folder: String(item.id) }) : navigate(`/i/${item.id}`);
  const title = project?.dock.find((t) => t.tool === 'vault')?.title ?? 'Docs';
  const crumbs = [
    { label: project?.name ?? '…', to: `/p/${id}` },
    { label: title, to: folderId ? `/p/${id}/docs` : undefined },
    ...(folder?.above ?? []).map((a, i, all) => ({
      label: a.title,
      to: i < all.length - 1 ? `/p/${id}/docs?folder=${a.id}` : undefined,
    })),
  ];
  const here = folder?.above.at(-1)?.title ?? title;
  return (
    <ProjectsShell project={project} title={`${here} · ${project?.name ?? ''}`}>
      <Perma>
        <Crumbs
          project={folderId ? null : project}
          crumbs={crumbs}
          right={
            <Menu
              items={[
                { label: "Open this folder's page", hidden: !folderId, onClick: () => navigate(`/i/${folderId}`) },
                {
                  label: layout === 'grid' ? 'Show as a list' : 'Show as a grid',
                  onClick: () => setView(layout === 'grid' ? 'list' : 'grid'),
                },
              ]}
            />
          }
        />
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="bc-title mr-auto text-2xl">{here}</h1>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            aria-label="Sort"
            className="bc-input w-auto py-1.5 text-[15px]"
          >
            <option value="name">A–Z</option>
            <option value="created">Newest</option>
            <option value="modified">Last changed</option>
          </select>
          <Menu
            label="New"
            items={[
              { label: '📁 New folder', onClick: () => setMaking('vault') },
              { label: '📄 New document', onClick: () => setMaking('document') },
              { label: '🔗 Link to a file elsewhere', onClick: () => setMaking('link') },
            ]}
          />
        </div>
        {making && (
          <NewThing
            kind={making}
            projectId={id}
            folderId={folderId}
            onDone={(made) => {
              setMaking('');
              if (made?.type === 'document') navigate(`/i/${made.id}`);
              else load();
            }}
          />
        )}
        {error && (
          <p role="alert" className="mt-3 text-bc-unread">
            {error}
          </p>
        )}
        {folder && folder.items.length === 0 && !making && (
          <div className="mt-6">
            <EmptyState title="Nothing here yet.">
              Make a folder, write a document, or link to a file in Google Drive, Dropbox or anywhere else.
            </EmptyState>
          </div>
        )}
        {layout === 'grid' ? (
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {folder?.items.map((i) => (
              <Tile key={i.id} item={i} onOpen={() => open(i)} />
            ))}
          </div>
        ) : (
          <ul className="mt-4">
            {folder?.items.map((i) => (
              <li key={i.id} className="border-b border-bc-line">
                <button
                  type="button"
                  onClick={() => open(i)}
                  className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-bc-wash"
                >
                  <span aria-hidden className={`bc-c-${i.color} text-2xl`}>
                    {ICON[i.type]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-bold">{i.title}</span>
                    <span className="block truncate text-[13px] text-bc-subtle">
                      {i.type === 'vault'
                        ? `${i.items_count ?? 0} items`
                        : i.type === 'link'
                          ? i.url
                          : plain(i.body).slice(0, 120)}
                    </span>
                  </span>
                  <span className="shrink-0 text-[13px] text-bc-subtle">{when(i.updated_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {folderId && (
          <p className="mt-6">
            <Link
              to={
                folder?.above.length && folder.above.length > 1
                  ? `/p/${id}/docs?folder=${folder.above[folder.above.length - 2].id}`
                  : `/p/${id}/docs`
              }
              className="text-bc-blue underline"
            >
              ← Up a folder
            </Link>
          </p>
        )}
      </Perma>
    </ProjectsShell>
  );
}
