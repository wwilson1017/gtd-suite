// Common Brain — what the search box in the nav (BrainShell) finds: memories, then pages,
// best match first (backend/brain.py search). The person's own searches are never misses.
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { searchBrain } from './api';
import type { SearchResult } from './types';
import { ago, who } from './util';

export function SearchResults({ q, onOpen }: { q: string; onOpen: () => void }) {
  const [found, setFound] = useState<SearchResult | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    searchBrain(q).then(
      (r) => {
        if (live) {
          setFound(r);
          setError('');
        }
      },
      (e) => {
        if (live) setError(apiErrorMessage(e, 'Could not search.'));
      },
    );
    return () => {
      live = false;
    };
  }, [q]);

  if (error)
    return (
      <p role="alert" className="text-sm text-[#ff9db0]">
        {error}
      </p>
    );
  if (!found) return <p className="text-sm text-muted">Searching…</p>;
  if (!found.memories.length && !found.pages.length) {
    return <p className="text-sm text-muted">Nothing in your brain holds “{q}”. Try other words.</p>;
  }
  return (
    <section aria-label="Search results" className="space-y-5">
      {found.memories.length > 0 && (
        <div className="cb-panel p-4">
          <h2 className="font-heading text-sm font-bold text-white">Memories</h2>
          <ul className="mt-2 divide-y divide-white/10">
            {found.memories.map((m) => (
              <li key={m.id} className="py-2 text-sm text-charcoal">
                {m.locked && '🔒 '}
                {m.text}
                <span className="ml-2 text-xs text-muted">
                  {who(m.updated_by)} · {ago(m.updated_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {found.pages.length > 0 && (
        <div className="cb-panel p-4">
          <h2 className="font-heading text-sm font-bold text-white">Pages</h2>
          <ul className="mt-2 divide-y divide-white/10">
            {found.pages.map((p) => (
              <li key={p.id} className="py-2">
                <Link
                  to={`/p/${p.id}`}
                  onClick={onOpen}
                  className="font-heading font-semibold text-white hover:underline"
                >
                  {p.title}
                </Link>
                <span className="ml-2 font-mono text-xs text-[#22d3ee]">{p.path}</span>
                <p className="mt-0.5 text-sm text-muted">{p.snippet}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
