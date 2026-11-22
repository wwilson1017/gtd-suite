import { BASE } from '../../core/app';
import { mayLockPage, showsViews, shortNameLabel } from '../../paid/features';
// Simple Sites — the home page: the account's pages and short links, a box to
// publish a page (pasted, or from a file) and one to make a short link. Agents do
// most publishing through the agent link; this is where the person sees it all,
// takes things down, and deletes (the one place anything is deleted).
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { SITE_MAX_BYTES } from './types';
import { apiErrorMessage } from '../../core/api/client';
import { CopyButton } from '../todo-gtd/components/CopyButton';
import { PlanCard } from '../../paid/PlanCard';
import { useSession } from '../todo-gtd/session';
import { createLink, createPage, deleteSite, downloadZip, listSites, updateSite } from './api';
import { SitesData } from './SitesData';
import { SitesShell } from './SitesShell';
import type { Site, SiteCaps } from './types';

function sizeLabel(bytes: number) {
  if (bytes === 0) return '0 KB';
  if (bytes < 1_000_000) return `${Math.max(1, Math.round(bytes / 1000))} KB`;
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
}

const inputCls =
  'min-w-0 rounded-lg border border-line bg-cream px-3 py-2 text-base sm:text-sm text-charcoal focus:border-brand focus:outline-none';
const btnCls =
  'shrink-0 rounded-lg bg-brand-dark px-4 py-2 font-heading text-sm text-white hover:bg-brand-deep disabled:opacity-40';
const smallBtn =
  'rounded-lg border border-line bg-cream px-3 py-1.5 text-sm font-heading text-charcoal hover:bg-sand disabled:opacity-40';
const NAME_HINT = 'Optional: up to 20 lowercase letters, digits or hyphens, shown in the address';

// Every folder's name, for the folder fields' suggestions (one <datalist> on the page).
const FOLDERS_LIST = 'site-folders';

/** Only what was filled in, so an empty form sends neither. */
function filed(note: string, folder: string): { note?: string; folder?: string } {
  return { ...(note.trim() ? { note } : {}), ...(folder.trim() ? { folder } : {}) };
}

/** A page's or link's private note and folder, as form fields. */
function Filing({
  note,
  folder,
  onNote,
  onFolder,
}: {
  note: string;
  folder: string;
  onNote: (v: string) => void;
  onFolder: (v: string) => void;
}) {
  const ids = { note: useId(), folder: useId() };
  return (
    <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_12rem]">
      <div>
        <label htmlFor={ids.note} className="block text-sm text-charcoal">
          Note <span className="text-muted">(only you see it)</span>
        </label>
        <input
          id={ids.note}
          value={note}
          onChange={(e) => onNote(e.target.value)}
          maxLength={500}
          placeholder="Who it is for"
          className={`${inputCls} mt-1 w-full`}
        />
      </div>
      <div>
        <label htmlFor={ids.folder} className="block text-sm text-charcoal">
          Folder
        </label>
        <input
          id={ids.folder}
          value={folder}
          onChange={(e) => onFolder(e.target.value)}
          maxLength={60}
          list={FOLDERS_LIST}
          placeholder="None"
          className={`${inputCls} mt-1 w-full`}
        />
      </div>
    </div>
  );
}

function Row({ site, onChanged, onError }: { site: Site; onChanged: () => void; onError: (message: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [now] = useState(Date.now);
  const live = site.status === 'published';
  // The account may add locks; taking a lock off is always allowed.
  const session = useSession().session;
  const canLock = site.kind === 'page' && mayLockPage(session);

  /** True when the action went through. */
  const run = async (action: () => Promise<unknown>, failed: string): Promise<boolean> => {
    setBusy(true);
    onError('');
    let ok = false;
    try {
      await action();
      onChanged();
      ok = true;
    } catch (e) {
      onError(apiErrorMessage(e, failed));
    }
    setBusy(false);
    return ok;
  };
  const remove = () => {
    const what = site.kind === 'page' ? 'page' : 'short link';
    if (
      !window.confirm(
        `Delete this ${what} for good?\n\n${site.address} stops working, and ` +
          'it cannot be brought back. Take it down instead to keep it.',
      )
    )
      return;
    void run(() => deleteSite(site.id), 'Could not delete it — try again.');
  };
  // A masked field, not window.prompt: the password never shows on screen.
  const [locking, setLocking] = useState(false);
  const [editing, setEditing] = useState(false);
  const [details, setDetails] = useState({ note: '', folder: '' });
  const startEditing = () => {
    setDetails({ note: site.note ?? '', folder: site.folder ?? '' });
    setEditing(true);
  };
  // Only the note and folder: filing never moves a page up the recent list.
  const saveDetails = async () => {
    if (await run(() => updateSite(site.id, details), 'Could not save it — try again.')) setEditing(false);
  };
  const [password, setPassword] = useState('');
  const lock = async () => {
    // Kept on a failure (busy, refused, offline), so the owner can simply try again.
    if (await run(() => updateSite(site.id, { password }), 'Could not lock it — try again.')) {
      setLocking(false);
      setPassword('');
    }
  };

  return (
    <li className="rounded-xl border border-line-faint bg-cream p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-heading font-bold text-charcoal">{site.title || 'Untitled'}</span>
        <span className="text-xs text-muted">
          {site.suspended_at ? 'Taken down by the operator' : live ? 'Live' : 'Taken down'}
          {site.kind === 'page' && ` · ${sizeLabel(site.size ?? site.bytes ?? 0)}`}
          {site.layout === 'files' && ` · ${site.file_count} files`}
          {` · ${site.updated_at.slice(0, 10)}`}
          {showsViews(site) && ` · ${site.views} ${site.views === 1 ? 'view' : 'views'}`}
          {site.locked && ' · 🔒 Password'}
        </span>
        {site.folder && (
          <span className="rounded-full bg-sand px-2 py-0.5 text-xs text-charcoal">📁 {site.folder}</span>
        )}
      </div>
      {site.expires_at && (
        <p className="mt-1 text-sm text-brand-ink">
          {Date.parse(site.expires_at) <= now
            ? 'This site is down'
            : `Comes down in ${Math.ceil((Date.parse(site.expires_at) - now) / 86_400_000)} days`}
          :{' '}
          <a href={BASE + '/app/connect/email'} className="underline">
            confirm your email
          </a>
          .
        </p>
      )}
      {site.note && <p className="mt-1 text-sm text-muted">{site.note}</p>}
      {site.kind === 'link' && <p className="mt-1 truncate text-xs text-muted">Goes to {site.target}</p>}
      <div className="mt-2 flex items-center gap-2">
        <a
          href={site.address}
          target="_blank"
          rel="noopener noreferrer"
          className={`min-w-0 truncate text-sm underline ${live ? 'text-brand-ink' : 'text-muted line-through'}`}
        >
          {site.address}
        </a>
        <CopyButton text={() => site.address} label="Copy the address" />
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          className={smallBtn}
          onClick={() =>
            void run(
              () => updateSite(site.id, { status: live ? 'unpublished' : 'published' }),
              'Could not change it — try again.',
            )
          }
        >
          {live ? 'Take down' : 'Put back up'}
        </button>
        {site.kind === 'page' && (
          <button
            type="button"
            disabled={busy}
            className={smallBtn}
            onClick={() => void run(() => downloadZip(site.id), 'Could not download the zip.')}
          >
            Download zip
          </button>
        )}
        {canLock && !locking && (
          <button type="button" disabled={busy} className={smallBtn} onClick={() => setLocking(true)}>
            {site.locked ? 'Change password' : 'Lock with a password'}
          </button>
        )}
        {site.locked && (
          <button
            type="button"
            disabled={busy}
            className={smallBtn}
            onClick={() => void run(() => updateSite(site.id, { password: '' }), 'Could not unlock it — try again.')}
          >
            Remove password
          </button>
        )}
        {!editing && (
          <button type="button" disabled={busy} className={smallBtn} onClick={startEditing}>
            Note &amp; folder
          </button>
        )}
        <button type="button" disabled={busy} className={smallBtn} onClick={remove}>
          Delete
        </button>
      </div>
      {site.kind === 'page' && <SitesData site={site} onChanged={onChanged} />}
      {editing && (
        <form
          className="mt-2"
          onSubmit={(e) => {
            e.preventDefault();
            void saveDetails();
          }}
        >
          <Filing
            note={details.note}
            folder={details.folder}
            onNote={(note) => setDetails((d) => ({ ...d, note }))}
            onFolder={(folder) => setDetails((d) => ({ ...d, folder }))}
          />
          <div className="mt-2 flex gap-2">
            <button type="submit" disabled={busy} className={btnCls}>
              Save
            </button>
            <button type="button" className={smallBtn} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {locking && (
        <form
          className="mt-2 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void lock();
          }}
        >
          <input
            type="password"
            autoComplete="new-password"
            autoFocus
            required
            minLength={4}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-label="Password for this page"
            placeholder="4 to 200 characters"
            className={`${inputCls} w-56`}
          />
          <button type="submit" disabled={busy || password.length < 4} className={btnCls}>
            Save
          </button>
          <button
            type="button"
            className={smallBtn}
            onClick={() => {
              setLocking(false);
              setPassword('');
            }}
          >
            Cancel
          </button>
          <p className="basis-full text-xs text-muted">
            Visitors type it once per device. Changing it asks everyone again.
          </p>
        </form>
      )}
    </li>
  );
}

function NewPage({ maxBytes = SITE_MAX_BYTES, onMade }: { maxBytes?: number; onMade: (site: Site) => void }) {
  const ids = { content: useId(), name: useId(), format: useId() };
  const [content, setContent] = useState('');
  const [format, setFormat] = useState<'markdown' | 'html'>('markdown');
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [folder, setFolder] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The form is held while a file is read, so nothing can be published, typed or
  // picked before its text is in the box.
  const [reading, setReading] = useState(false);

  const fromFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > maxBytes) {
      setError(`A page is at most ${maxBytes / 1_000_000} MB.`);
      return;
    }
    setError('');
    setReading(true);
    const text = await file.text().catch(() => null);
    setReading(false);
    if (text === null) {
      setError('Could not read that file.');
      return;
    }
    setContent(text);
    setFormat(/\.html?$/i.test(file.name) ? 'html' : 'markdown');
  };
  const publish = async () => {
    setBusy(true);
    setError('');
    try {
      onMade(
        await createPage({ content, format, name: name.trim().toLowerCase() || undefined, ...filed(note, folder) }),
      );
      setContent('');
      setName('');
      setNote('');
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not publish it — try again.'));
    }
    setBusy(false);
  };

  return (
    <form
      className="rounded-xl border border-line-faint bg-cream p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void publish();
      }}
    >
      {/* Held while publishing, so nothing typed meanwhile is cleared by the success. */}
      <fieldset disabled={busy || reading}>
        <h2 className="font-heading text-base font-bold text-charcoal">New page</h2>
        <label htmlFor={ids.content} className="mt-2 block text-sm text-charcoal">
          Paste Markdown or HTML, or pick a file
        </label>
        <textarea
          id={ids.content}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={6}
          className={`${inputCls} mt-1 w-full font-mono`}
          placeholder="# My page"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            type="file"
            accept=".md,.markdown,.txt,.html,.htm"
            aria-label="Pick a file"
            onChange={(e) => {
              // Taken into the box, then cleared, so the same file can be picked again.
              void fromFile(e.target.files?.[0]);
              e.target.value = '';
            }}
            className="text-sm text-muted"
          />
          <label htmlFor={ids.format} className="sr-only">
            Format
          </label>
          <select
            id={ids.format}
            value={format}
            onChange={(e) => setFormat(e.target.value as 'markdown' | 'html')}
            className={inputCls}
          >
            <option value="markdown">Markdown</option>
            <option value="html">HTML</option>
          </select>
        </div>
        <label htmlFor={ids.name} className="mt-2 block text-sm text-charcoal">
          Name
        </label>
        <input
          id={ids.name}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={20}
          placeholder="menu"
          title={NAME_HINT}
          className={`${inputCls} mt-1 w-40`}
        />
        <p className="mt-1 text-xs text-muted">{NAME_HINT}.</p>
        <Filing note={note} folder={folder} onNote={setNote} onFolder={setFolder} />
        <button type="submit" disabled={!content.trim()} className={`${btnCls} mt-3`}>
          {busy ? 'Publishing…' : 'Publish'}
        </button>
      </fieldset>
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </form>
  );
}

// The server's cap decides: 0 on a hosted account until its email is confirmed, and
// never 0 on a one-list self-host. Undefined while the list loads.
function NewLink({ cap, onMade }: { cap: number | undefined; onMade: (site: Site) => void }) {
  const session = useSession().session;
  const mail = session?.mail === true;
  const ids = { url: useId(), name: useId(), short: useId() };
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [shortName, setShortName] = useState('');
  const [note, setNote] = useState('');
  const [folder, setFolder] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const make = async () => {
    setBusy(true);
    setError('');
    try {
      onMade(
        await createLink({
          url: url.trim(),
          name: name.trim().toLowerCase() || undefined,
          ...(shortName.trim() ? { short_name: shortName.trim() } : {}),
          ...filed(note, folder),
        }),
      );
      setUrl('');
      setName('');
      setShortName('');
      setNote('');
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not make it — try again.'));
    }
    setBusy(false);
  };

  return (
    <form
      className="rounded-xl border border-line-faint bg-cream p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void make();
      }}
    >
      <fieldset disabled={busy || !cap}>
        <h2 className="font-heading text-base font-bold text-charcoal">New short link</h2>
        {cap === 0 && (
          <p className="mt-1 text-sm text-muted">
            {mail
              ? 'Short links need a confirmed email. Add one in Settings.'
              : 'Short links need a confirmed email, and this server sends no mail, so they are off here.'}
          </p>
        )}
        <label htmlFor={ids.url} className="mt-2 block text-sm text-charcoal">
          Goes to
        </label>
        <input
          id={ids.url}
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
          className={`${inputCls} mt-1 w-full`}
        />
        <label htmlFor={ids.name} className="mt-2 block text-sm text-charcoal">
          Name
        </label>
        <input
          id={ids.name}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={20}
          placeholder="docs"
          title={NAME_HINT}
          className={`${inputCls} mt-1 w-40`}
        />
        <label htmlFor={ids.short} className="mt-2 block text-sm text-charcoal">
          {shortNameLabel(session)}
        </label>
        <input
          id={ids.short}
          value={shortName}
          onChange={(e) => setShortName(e.target.value)}
          minLength={4}
          maxLength={30}
          pattern="[a-z0-9-]{4,30}"
          placeholder="vancouver"
          className={`${inputCls} mt-1 w-full`}
        />
        <Filing note={note} folder={folder} onNote={setNote} onFolder={setFolder} />
        <button type="submit" disabled={!url.trim()} className={`${btnCls} mt-3 block`}>
          {busy ? 'Making…' : 'Make a short link'}
        </button>
      </fieldset>
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </form>
  );
}

export function SitesPage() {
  const sessionCaps = useSession().session?.caps;
  const [sites, setSites] = useState<Site[] | null>(null);
  const [caps, setCaps] = useState<SiteCaps | null>(null);
  const storageQuota = caps?.storage ?? sessionCaps?.storage;
  const storageUsed = caps?.storage_used ?? sessionCaps?.storage_used ?? 0;
  const [made, setMade] = useState<Site | null>(null);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const latest = useRef(0);

  const load = useCallback(() => {
    // Only the newest answer counts, failed or not: an older one arriving last would
    // bring back a deleted row, hide a new one, or show an error already put right.
    const asked = ++latest.current;
    listSites().then(
      (r) => {
        if (asked !== latest.current) return;
        setSites(r.sites);
        setCaps(r.caps);
        setLoadError('');
      },
      (e) => {
        if (asked === latest.current) setLoadError(apiErrorMessage(e, 'Could not load your sites.'));
      },
    );
  }, []);
  useEffect(load, [load]);
  const onMade = (site: Site) => {
    setMade(site);
    load();
  };
  // A row changed: the "made" note may now point at something taken down or deleted.
  const onChanged = () => {
    setMade(null);
    load();
  };

  // Filtered here, over the whole list (at most a few hundred rows): instant, and the
  // "x of cap" counts stay the account's.
  const [query, setQuery] = useState('');
  const [folder, setFolder] = useState<string | null>(null); // null: all; '': in none
  const folders = [...new Set((sites ?? []).map((s) => s.folder ?? '').filter(Boolean))].sort((a, b) =>
    a.localeCompare(b),
  );
  // As the server's casefold(): up then down, then the two letters that still differ (ß, final ς).
  const fold = (t: string) => t.toUpperCase().toLowerCase().replace(/ß/g, 'ss').replace(/ς/g, 'σ');
  const words = fold(query).split(/\s+/).filter(Boolean);
  const shown = (s: Site) =>
    (folder === null || (s.folder ?? '') === folder) &&
    words.every((w) =>
      [s.title, s.note, s.folder, s.name, s.code, s.target, s.address].some((f) => fold(f ?? '').includes(w)),
    );
  const pages = sites?.filter((s) => s.kind === 'page') ?? [];
  const links = sites?.filter((s) => s.kind === 'link') ?? [];
  const filtering = folder !== null || words.length > 0;
  const section = (title: string, all: Site[], cap: number | undefined, empty: string) => {
    const rows = all.filter(shown);
    return (
      <section>
        <h2 className="font-heading text-lg font-bold text-charcoal">
          {title}
          {!!cap && (
            <span className="ml-2 text-sm font-normal text-muted">
              {all.length} of {cap}
            </span>
          )}
        </h2>
        {sites && rows.length === 0 && (
          <p className="mt-1 text-sm text-muted">{filtering && all.length ? 'None match.' : empty}</p>
        )}
        <ul className="mt-2 space-y-2">
          {rows.map((site) => (
            <Row key={site.id} site={site} onChanged={onChanged} onError={setError} />
          ))}
        </ul>
      </section>
    );
  };

  return (
    <SitesShell>
      <div className="mx-auto max-w-shell space-y-6">
        <p className="text-sm text-muted">
          Ask your AI to publish a page: it gets a short address to hand you. Pages are unlisted (only people with the
          address can open them) and can be taken down any time.
        </p>
        <PlanCard />
        {storageQuota !== undefined && (
          <div className="text-xs text-muted">
            <label htmlFor="site-storage">
              Storage: {sizeLabel(storageUsed)} of {sizeLabel(storageQuota)} · shared with Brain files
            </label>
            <meter
              id="site-storage"
              min={0}
              max={storageQuota}
              value={storageUsed}
              className="mt-1 block h-2 w-full accent-brand"
            />
          </div>
        )}
        {loadError && (
          <p role="alert" className="text-sm text-brand-ink">
            {loadError}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-brand-ink">
            {error}
          </p>
        )}
        {made && (
          <p
            role="status"
            className="flex flex-wrap items-center gap-2 rounded-xl border border-line-faint bg-cream p-3 text-sm text-charcoal"
          >
            {made.kind === 'page' ? 'Published at' : 'Made a short link:'}
            <a href={made.address} target="_blank" rel="noopener noreferrer" className="text-brand-ink underline">
              {made.address}
            </a>
            <CopyButton text={() => made.address} label="Copy the address" />
          </p>
        )}
        <datalist id={FOLDERS_LIST}>
          {folders.map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>
        {!!sites?.length && (
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search pages and links"
              placeholder="Search titles, notes, addresses"
              className={`${inputCls} min-w-0 flex-1`}
            />
            <select
              aria-label="Folder"
              value={folder ?? '\u0000all'}
              className={inputCls}
              onChange={(e) => setFolder(e.target.value === '\u0000all' ? null : e.target.value)}
            >
              <option value={'\u0000all'}>All folders</option>
              {folders.map((f) => (
                <option key={f} value={f}>
                  📁 {f}
                </option>
              ))}
              <option value="">No folder</option>
            </select>
          </div>
        )}
        {section('Pages', pages, caps?.pages, 'No pages yet.')}
        {section('Short links', links, caps?.links, 'No short links yet.')}
        <NewPage maxBytes={caps?.page_bytes} onMade={onMade} />
        <NewLink cap={caps?.links} onMade={onMade} />
      </div>
    </SitesShell>
  );
}
