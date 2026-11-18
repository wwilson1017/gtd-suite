import { useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { importMarkdown, type ImportReport } from './api';

export function ImportMarkdown() {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [archive, setArchive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const [error, setError] = useState('');
  async function submit(dryRun: boolean) {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      setReport(await importMarkdown(file, dryRun, archive));
      setPreview(dryRun);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not import this zip.'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="cb-panel p-5">
      <h2 className="font-heading text-lg font-bold text-white">Import Markdown</h2>
      <p className="mt-1 text-sm text-muted">
        Bring a zip of Markdown, HTML, memories and attachments. Preview it before importing. Up to 200 MB.
      </p>
      <input
        type="file"
        accept=".zip,application/zip"
        aria-label="Choose a zip"
        disabled={busy}
        className="mt-3 block w-full text-sm text-charcoal"
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          setReport(null);
          setPreview(false);
          setError('');
        }}
      />
      <label className="mt-3 flex items-start gap-2 text-sm text-muted">
        <input type="checkbox" checked={archive} disabled={busy} onChange={(e) => setArchive(e.target.checked)} />
        Archive pages and memories missing from this zip, and missing files previously imported from a zip with this
        name.
      </label>
      {archive && (
        <p className="mt-2 text-sm text-muted">
          Pause other writers during the import. Missing items are archived only after every entry is processed.
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button className="cb-btn-ghost text-sm" disabled={!file || busy} onClick={() => void submit(true)}>
          Preview import
        </button>
        {preview && report?.complete && (
          <button className="cb-btn text-sm" disabled={busy} onClick={() => void submit(false)}>
            Import
          </button>
        )}
      </div>
      {busy && (
        <p role="status" className="mt-3 text-sm text-muted">
          Processing the zip…
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
          {error}
        </p>
      )}
      {report && (
        <div className="mt-3 space-y-2 text-sm text-charcoal">
          <p>
            {report.counts.pages} pages, {report.counts.memories} memories, {report.counts.files} files.
          </p>
          {!preview && (
            <p>
              {report.complete ? 'Import complete.' : 'Import stopped.'} {report.processed} processed: {report.written}{' '}
              saved, {report.skipped} skipped, {report.archived} archived.
            </p>
          )}
          {report.error && <p role="alert">{report.error} Run it again to resume.</p>}
          {report.over_cap.length > 0 && (
            <p>Over the current cap: {report.over_cap.join(', ')}. The import stops when it reaches the cap.</p>
          )}
          <details>
            <summary className="cursor-pointer">Paths and import details</summary>
            <ul className="mt-2 max-h-80 space-y-1 overflow-auto break-words">
              {report.path_changes.map((p, i) => (
                <li key={`p${i}`}>
                  {p.from} → {p.to}
                </li>
              ))}
              {report.removed.map((r, i) => (
                <li key={`r${i}`}>
                  {r.path}: blanked {r.counts.map((c) => `${c.count} ${c.kind}`).join(', ')}
                </li>
              ))}
              {report.oversized.map((p) => (
                <li key={`o${p}`}>{p}: oversized page becomes a file</li>
              ))}
              {report.decoded.map((p) => (
                <li key={`d${p}`}>{p}: invalid UTF-8 replaced</li>
              ))}
              {report.warnings.map((w, i) => (
                <li key={`w${i}`}>
                  {w.path}: {w.reason}
                </li>
              ))}
              {report.entries.map((e, i) => (
                <li key={`e${i}`}>
                  {e.path} ({e.kind}): {preview ? e.planned : e.result}
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}
