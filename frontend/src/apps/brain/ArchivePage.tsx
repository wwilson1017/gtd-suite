// Common Brain — the archive: memories and pages no longer in use. Nothing here is
// gone: bring any of it back, or forget it for good.
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { getArchive, updateMemory, updatePage } from './api';
import { BrainShell } from './BrainShell';
import type { Memory, PageSummary } from './types';
import { ago, who } from './util';

export function ArchivePage() {
  const [data, setData] = useState<{ memories: Memory[]; pages: PageSummary[] } | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    getArchive().then(setData, (e) => setError(apiErrorMessage(e, 'Could not load the archive.')));
  }, []);
  useEffect(load, [load]);
  const back = async (run: () => Promise<unknown>) => {
    try {
      await run();
      load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not bring it back.'));
    }
  };
  return (
    <BrainShell title="Archive">
      <h1 className="font-heading text-2xl font-bold text-white">Archive</h1>
      <p className="mt-1 text-sm text-muted">
        What is no longer true or in use. AIs archive instead of deleting, so nothing is lost.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
          {error}
        </p>
      )}
      {data && (
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <section className="cb-panel p-4">
            <h2 className="font-heading font-bold text-white">Memories</h2>
            {data.memories.length === 0 && <p className="mt-3 text-sm text-muted">None.</p>}
            <ul className="mt-2 divide-y divide-white/10">
              {data.memories.map((m) => (
                <li key={m.id} className="py-2 text-sm">
                  <p className="text-charcoal">{m.text}</p>
                  <p className="mt-1 flex gap-3 text-xs text-muted">
                    <span>
                      {who(m.updated_by)} · {ago(m.updated_at)}
                    </span>
                    <button
                      type="button"
                      className="hover:text-white"
                      onClick={() => void back(() => updateMemory(m.id, { status: 'active', version: m.version }))}
                    >
                      Bring back
                    </button>
                    <Link to={`/forget/memory/${m.id}`} className="hover:text-[#ff9db0]">
                      Forget
                    </Link>
                  </p>
                </li>
              ))}
            </ul>
          </section>
          <section className="cb-panel p-4">
            <h2 className="font-heading font-bold text-white">Pages</h2>
            {data.pages.length === 0 && <p className="mt-3 text-sm text-muted">None.</p>}
            <ul className="mt-2 divide-y divide-white/10">
              {data.pages.map((p) => (
                <li key={p.id} className="py-2 text-sm">
                  <Link to={`/p/${p.id}`} className="text-white hover:underline">
                    {p.title}
                  </Link>
                  <span className="ml-2 font-mono text-xs text-muted">{p.path}</span>
                  <p className="mt-1 flex gap-3 text-xs text-muted">
                    <span>
                      {who(p.updated_by)} · {ago(p.updated_at)}
                    </span>
                    <button
                      type="button"
                      className="hover:text-white"
                      onClick={() => void back(() => updatePage(p.id, { status: 'active', version: p.version }))}
                    >
                      Bring back
                    </button>
                  </p>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </BrainShell>
  );
}
