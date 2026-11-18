// Common Brain — one page: Markdown rendered (raw HTML skipped), or an HTML page in a
// sandbox with no access to this site (an opaque origin: no cookies, no app). Edit,
// history, Share to Sites, archive, forget. A Markdown page's frontmatter shows as a
// properties box, and its [[links]] (wikilinks.ts) are resolved in one batch when it opens:
// a known one opens that page, an unknown one stays text with a dotted underline.
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Components } from 'react-markdown';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { Markdown } from '../notes-gtd/Markdown';
import { useSession } from '../todo-gtd/session';
import { download, getPage, resolveLinks, sharePage, updatePage } from './api';
import { BrainShell } from './BrainShell';
import { MoveToBrain } from './MoveToBrain';
import { HistoryDialog } from './HistoryDialog';
import type { Page } from './types';
import { ago, removedNote, splitFront, who } from './util';
import { remarkWikilinks, WIKI_HREF, wikiTargets } from './wikilinks';

const PLUGINS = [remarkWikilinks];
type Links = Awaited<ReturnType<typeof resolveLinks>>;

/** Links in the page: a [[link]] in the app (or plain text when it leads nowhere), any other a new tab. */
const anchor =
  (links: Links): Components['a'] =>
  ({ node: _node, href, children, ...props }) => {
    void _node; // react-markdown metadata must not become a DOM attribute.
    if (!href?.startsWith(WIKI_HREF)) {
      return (
        <a {...props} href={href} target="_blank" rel="noopener noreferrer" className="text-brand-ink underline">
          {children}
        </a>
      );
    }
    let key = href.slice(WIKI_HREF.length);
    try {
      key = decodeURIComponent(key);
    } catch {
      /* a hand-written bad escape: unresolved */
    }
    const hit = Object.hasOwn(links, key) ? links[key] : undefined;
    if (hit?.kind === 'file') {
      const name = hit.path.slice(hit.path.lastIndexOf('/') + 1);
      return (
        <button
          type="button"
          className="text-brand-ink underline"
          onClick={() => void download(`/files/${hit.id}`, name).catch(() => {})}
        >
          {children}
        </button>
      );
    }
    return hit ? (
      <Link to={`/p/${hit.id}`} className="text-brand-ink underline">
        {children}
      </Link>
    ) : (
      <span className="cb-wiki-missing" title="Nothing in your brain by that name yet">
        {children}
      </span>
    );
  };

export function PageView() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState('');
  const [history, setHistory] = useState(false);
  const [shared, setShared] = useState('');
  const [notice, setNotice] = useState('');
  const [links, setLinks] = useState<Links>({});
  const navigate = useNavigate();
  const sitesOn = useSession().session?.apps.includes('sites') ?? false;
  const editing = params.get('edit') === '1';

  const load = useCallback(() => {
    getPage(id).then(
      (p) => {
        setPage(p);
        setError('');
      },
      (e) => setError(apiErrorMessage(e, 'Could not open the page.')),
    );
  }, [id]);
  useEffect(load, [load]);
  const markdown = page?.format === 'markdown' ? page.body : '';
  const { props, rest } = useMemo(() => splitFront(markdown), [markdown]);
  useEffect(() => {
    const targets = wikiTargets(markdown);
    let live = true;
    if (targets.length)
      resolveLinks(targets).then(
        (l) => {
          if (live) setLinks(l);
        },
        () => {},
      );
    return () => {
      live = false;
    };
  }, [markdown]);
  const components = useMemo(() => ({ a: anchor(links) }), [links]);

  const change = async (fields: Parameters<typeof updatePage>[1]) => {
    if (!page) return;
    try {
      const saved = await updatePage(page.id, { ...fields, version: page.version });
      setPage(saved);
      setNotice(removedNote(saved.removed));
      setError('');
      return true;
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? 'An AI changed this page while you were editing. Your text is still here: copy it, then reload.'
          : apiErrorMessage(e, 'Could not save it.'),
      );
      return false;
    }
  };
  const share = async () => {
    try {
      setShared((await sharePage(id)).address);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not share it.'));
    }
  };

  return (
    <BrainShell title={page?.title}>
      <Link to="/" className="text-sm text-muted hover:text-white">
        ← Your brain
      </Link>
      {error && (
        <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-3 text-sm text-[#ffcf9d]">
          {notice}
        </p>
      )}
      {page && !editing && (
        <article className="mt-3">
          <p className="font-mono text-xs text-[#22d3ee]">
            {page.path}
            {page.format === 'html' ? ' · HTML' : ''}
          </p>
          <h1 className="mt-1 font-heading text-3xl font-bold tracking-tight text-white">{page.title}</h1>
          <p className="mt-1 text-xs text-muted">
            {who(page.updated_by)} changed it {ago(page.updated_at)} · version {page.version}
            {page.status === 'archived' && ' · archived'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            <button type="button" onClick={() => setParams({ edit: '1' })} className="cb-btn px-4 py-1.5 text-sm">
              Edit
            </button>
            <MoveToBrain kind="page" id={id} version={page.version} path={page.path} onMoved={() => navigate('/')} />
            <button type="button" onClick={() => setHistory(true)} className="cb-btn-ghost">
              History
            </button>
            {sitesOn && (
              <button type="button" onClick={() => void share()} className="cb-btn-ghost">
                Share to Sites
              </button>
            )}
            <button
              type="button"
              onClick={() => void change({ status: page.status === 'archived' ? 'active' : 'archived' })}
              className="cb-btn-ghost"
            >
              {page.status === 'archived' ? 'Bring back' : 'Archive'}
            </button>
            <button
              type="button"
              onClick={() => navigate(`/forget/page/${page.id}`)}
              className="cb-btn-ghost hover:text-[#ff9db0]"
            >
              Forget
            </button>
          </div>
          {shared && (
            <p role="status" className="mt-3 text-sm text-charcoal">
              Shared on Simple Sites:{' '}
              <a href={shared} target="_blank" rel="noopener noreferrer" className="text-[#22d3ee] underline break-all">
                {shared}
              </a>
            </p>
          )}
          {props.length > 0 && (
            <dl
              aria-label="Properties"
              className="cb-panel mt-5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 px-5 py-3 text-sm"
            >
              {props.map(([k, v], i) => [
                <dt key={`k${i}`} className="font-mono text-xs leading-5 text-muted">
                  {k}
                </dt>,
                <dd key={`v${i}`} className="break-words text-charcoal">
                  {v}
                </dd>,
              ])}
            </dl>
          )}
          <div className="cb-panel mt-5 p-5">
            {page.format === 'html' ? (
              <iframe
                title={page.title}
                sandbox="allow-scripts"
                srcDoc={page.body}
                className="h-[70vh] w-full rounded-lg bg-white"
              />
            ) : rest.trim() ? (
              <Markdown
                body={rest}
                plugins={PLUGINS}
                components={components}
                className="cb-md text-[15px] leading-relaxed text-charcoal"
              />
            ) : (
              <p className="text-sm text-muted">This page is empty.</p>
            )}
          </div>
        </article>
      )}
      {page && editing && (
        <PageEditor
          page={page}
          onCancel={() => setParams({})}
          onSave={async (fields) => {
            if (await change(fields)) setParams({});
          }}
        />
      )}
      {!page && !error && <p className="mt-4 text-sm text-muted">Loading…</p>}
      {history && <HistoryDialog kind="page" id={id} onClose={() => setHistory(false)} onRestored={load} />}
    </BrainShell>
  );
}

function PageEditor({
  page,
  onSave,
  onCancel,
}: {
  page: Page;
  onSave: (fields: { title: string; path: string; format: Page['format']; body: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(page.title);
  const [path, setPath] = useState(page.path);
  const [format, setFormat] = useState(page.format);
  const [body, setBody] = useState(page.body);
  const field = 'w-full rounded-lg border border-line bg-sand px-3 py-2 text-base text-charcoal sm:text-sm';
  return (
    <form
      className="mt-3 space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        void onSave({ title, path, format, body });
      }}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="Title"
        placeholder="Title"
        className={`${field} font-heading text-xl font-bold`}
      />
      <div className="flex flex-wrap gap-2">
        <input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          aria-label="Path"
          className={`${field} min-w-0 flex-1 font-mono`}
        />
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as Page['format'])}
          aria-label="Format"
          className="rounded-lg border border-line bg-sand px-2 text-sm text-charcoal"
        >
          <option value="markdown">Markdown</option>
          <option value="html">HTML</option>
        </select>
      </div>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        aria-label="The page"
        rows={20}
        className={`${field} font-mono leading-relaxed`}
      />
      <div className="flex gap-2">
        <button type="submit" className="cb-btn px-5 py-2 text-sm">
          Save
        </button>
        <button type="button" onClick={onCancel} className="cb-btn-ghost text-sm">
          Cancel
        </button>
      </div>
    </form>
  );
}
