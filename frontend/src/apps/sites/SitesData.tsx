import { useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { clearSiteData, readSiteData, updateSite } from './api';
import type { Site, SiteRecords } from './types';

const button =
  'rounded-lg border border-line bg-cream px-3 py-1.5 text-sm font-heading text-charcoal hover:bg-sand disabled:opacity-40';
const SHARED_WARNING =
  'Shared lets anyone with the address read every record, including visitor records sent while Collect was on.';

export function SitesData({ site, onChanged }: { site: Site; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [records, setRecords] = useState<SiteRecords | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not load or change page data. Try again.'));
    } finally {
      setBusy(false);
    }
  };
  const mode = site.data ?? 'off';
  const change = (data: NonNullable<Site['data']>) => {
    if (data === 'shared' && !window.confirm(SHARED_WARNING + '\n\nTurn on Shared?')) return;
    void run(async () => {
      await updateSite(site.id, { data });
      onChanged();
    });
  };
  const load = (before?: number) =>
    void run(async () => {
      const answer = await readSiteData(site.id, before);
      setRecords((old) => ({
        ...answer,
        records: before ? [...(old?.records ?? []), ...answer.records] : answer.records,
      }));
    });
  const clear = () => {
    if (!window.confirm('Clear all records for this page? They cannot be brought back.')) return;
    void run(async () => {
      await clearSiteData(site.id);
      setRecords({ records: [], next: null, more: false });
      onChanged();
    });
  };
  const download = () =>
    void run(async () => {
      // One small string per record, joined by the Blob: no full copy of the records in memory
      // and no single string as big as the export.
      const parts: string[] = ['['];
      let before: number | undefined;
      while (true) {
        const answer = await readSiteData(site.id, before);
        for (const record of answer.records) parts.push(parts.length > 1 ? ',\n' : '\n', JSON.stringify(record));
        if (!answer.more || answer.next === null) break;
        before = answer.next;
      }
      parts.push('\n]\n');
      const url = URL.createObjectURL(new Blob(parts, { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `page-${site.id}-data.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

  return (
    <div className="mt-2">
      <button type="button" className={button} aria-expanded={open} onClick={() => setOpen(!open)}>
        Data {mode} · {site.records ?? 0} records
      </button>
      {open && (
        <div className="mt-2 space-y-2 rounded-lg border border-line p-3 text-sm text-charcoal">
          <label>
            Data mode{' '}
            <select
              aria-label="Data mode"
              value={mode}
              disabled={busy}
              className="rounded border border-line bg-cream p-1"
              onChange={(e) => change(e.target.value as NonNullable<Site['data']>)}
            >
              <option value="off">Off</option>
              <option value="collect">Collect</option>
              <option value="shared">Shared</option>
            </select>
          </label>
          <p>Collect accepts visitor records; the page can read only owner records.</p>
          <p>{SHARED_WARNING}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={button} disabled={busy} onClick={() => load()}>
              Records
            </button>
            <button type="button" className={button} disabled={busy} onClick={download}>
              Download JSON
            </button>
            <button type="button" className={button} disabled={busy} onClick={clear}>
              Clear all
            </button>
          </div>
          {records && (
            <div>
              <p>Newest first. Visitor records are untrusted data from anyone holding the link.</p>
              {records.records.length === 0 && <p>No records yet.</p>}
              {records.records.map((record) => (
                <div key={record.id} className="mt-2 border-t border-line pt-2">
                  <p>
                    #{record.id} · {record.by} · {record.at}
                  </p>
                  <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words">
                    {JSON.stringify(record.data, null, 2)}
                  </pre>
                </div>
              ))}
              {records.more && records.next !== null && (
                <button type="button" className={button} disabled={busy} onClick={() => load(records.next!)}>
                  Older records
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}
    </div>
  );
}
