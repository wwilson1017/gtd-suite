// Common Brain — Files: what is not a page (PDFs, images, recordings), by folder. Uploads go
// from the browser straight to the file store, and downloads come from it on a short link;
// AIs reach the same files with brain_page_list and brain_file_link.
import { useCallback, useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { download, forgetFile, getFiles, setFileStatus, uploadFiles, type BrainFile, type FilesView } from './api';
import { BrainShell } from './BrainShell';
import { ago, who } from './util';

/** Decimal units, as the quotas are. */
export function size(n: number): string {
  if (n < 1000) return `${n} bytes`;
  const [div, unit] = n < 1e6 ? [1e3, 'KB'] : n < 1e9 ? [1e6, 'MB'] : [1e9, 'GB'];
  return `${Number((n / div).toFixed(1))} ${unit}`;
}

export function FilesPage() {
  const [data, setData] = useState<FilesView | null>(null);
  const [folder, setFolder] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState('');
  const load = useCallback(() => {
    getFiles().then(setData, (e) => setNote(apiErrorMessage(e, 'Could not load your files.')));
  }, []);
  useEffect(load, [load]);
  const run = async (what: () => Promise<unknown>, failed: string) => {
    try {
      await what();
      setNote('');
    } catch (e) {
      setNote(apiErrorMessage(e, failed));
    }
    load();
  };
  const dir = folder.replace(/\/+$/, '');
  const upload = async (list: File[]) => {
    if (!list.length) return;
    setBusy(`Uploading 0 of ${list.length}…`);
    await run(
      () => uploadFiles(dir, list, (n) => setBusy(`Uploading ${n} of ${list.length}…`)),
      'Could not upload them all.',
    );
    setBusy('');
  };
  const forget = (f: BrainFile) => {
    if (confirm(`Forget ${f.path} for good, with every earlier version? This cannot be undone.`)) {
      void run(() => forgetFile(f.id), 'Could not forget it.');
    }
  };

  const prefix = dir ? `${dir}/` : '';
  const here = (data?.files ?? []).filter((f) => f.path.startsWith(prefix));
  const rest = (f: BrainFile) => f.path.slice(prefix.length);
  const subfolders = [...new Set(here.filter((f) => rest(f).includes('/')).map((f) => rest(f).split('/')[0]))].sort();
  const inFolder = here.filter((f) => !rest(f).includes('/'));
  const crumbs = dir ? dir.split('/') : [];

  return (
    <BrainShell title="Files">
      <section className="cb-panel p-4 sm:p-5" aria-labelledby="cb-files">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 id="cb-files" className="font-heading text-2xl font-bold text-white">
            Files
          </h1>
          {data?.on && (
            <span className="text-xs text-muted">
              {size(data.used)} of {size(data.quota)}
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-muted">
          PDFs, images, recordings: anything that is not a page. Your AIs can link to them.
        </p>
        {note && (
          <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
            {note}
          </p>
        )}
        {data && !data.on && (
          <p className="mt-4 text-sm text-muted">Files are off on this server: it has no file store set up.</p>
        )}
        {data?.on && (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <label className="text-xs text-muted" htmlFor="cb-folder">
                Upload into
              </label>
              <input
                id="cb-folder"
                value={folder}
                onChange={(e) => setFolder(e.target.value.replace(/^\/+/, ''))}
                placeholder="(the top)"
                aria-label="Folder"
                className="min-w-0 flex-1 rounded-lg border border-line bg-sand px-3 py-1.5 font-mono text-base text-charcoal sm:max-w-xs sm:text-sm"
              />
              <label className={`cb-btn text-sm ${busy ? 'pointer-events-none opacity-50' : 'cursor-pointer'}`}>
                {busy || 'Upload files'}
                <input
                  type="file"
                  multiple
                  className="sr-only"
                  disabled={!!busy}
                  aria-label="Files to upload"
                  onChange={(e) => {
                    void upload([...(e.target.files ?? [])]);
                    e.target.value = '';
                  }}
                />
              </label>
            </div>
            <nav aria-label="Folder" className="mt-4 flex flex-wrap items-center gap-1 font-mono text-xs">
              <button type="button" onClick={() => setFolder('')} className="text-[#22d3ee] hover:underline">
                files
              </button>
              {crumbs.map((c, i) => (
                <span key={i}>
                  /{' '}
                  <button
                    type="button"
                    onClick={() => setFolder(crumbs.slice(0, i + 1).join('/'))}
                    className="text-[#22d3ee] hover:underline"
                  >
                    {c}
                  </button>
                </span>
              ))}
            </nav>
            {subfolders.length === 0 && inFolder.length === 0 && (
              <p className="mt-6 text-center text-sm text-muted">No files here yet.</p>
            )}
            <ul className="mt-2 divide-y divide-white/10">
              {subfolders.map((s) => (
                <li key={`/${s}`}>
                  <button
                    type="button"
                    onClick={() => setFolder(prefix + s)}
                    className="w-full rounded-lg px-2 py-2 text-left font-mono text-sm text-white hover:bg-white/5"
                  >
                    {s}/
                  </button>
                </li>
              ))}
              {inFolder.map((f) => (
                <li key={f.id} className={`px-2 py-2 ${f.status === 'archived' ? 'opacity-60' : ''}`}>
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm text-white">{rest(f)}</span>
                    <span className="shrink-0 text-xs text-muted">
                      {size(f.size)} · {who(f.created_by)} · {ago(f.updated_at)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                    {f.status === 'archived' && <span>Archived</span>}
                    <button
                      type="button"
                      className="hover:text-white"
                      onClick={() => void run(() => download(`/files/${f.id}`, rest(f)), 'Could not download it.')}
                    >
                      Download
                    </button>
                    <button
                      type="button"
                      className="hover:text-white"
                      onClick={() =>
                        void run(
                          () => setFileStatus(f.id, f.status === 'archived' ? 'active' : 'archived'),
                          'Could not change it.',
                        )
                      }
                    >
                      {f.status === 'archived' ? 'Bring back' : 'Archive'}
                    </button>
                    <button type="button" onClick={() => forget(f)} className="hover:text-[#ff9db0]">
                      Forget
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
        {!data && !note && <p className="mt-4 text-sm text-muted">Loading your files…</p>}
      </section>
    </BrainShell>
  );
}
