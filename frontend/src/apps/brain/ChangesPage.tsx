// Common Brain — what changed: every write, newest first, with which AI (or You) made
// it and when, grouped by consecutive passes or days.
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { getChanges } from './api';
import { BrainShell } from './BrainShell';
import type { Change } from './types';
import { ACTIONS, ago, who } from './util';

export function ChangesPage() {
  const [changes, setChanges] = useState<Change[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    getChanges().then(setChanges, (e) => setError(apiErrorMessage(e, 'Could not load the changes.')));
  }, []);
  const groups: { heading: string; reason: string; list: Change[] }[] = [];
  let previous = '';
  for (const c of changes ?? []) {
    const day = new Date(c.at).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
    const key = c.pass ? `pass:${c.pass}` : `day:${day}`;
    if (key !== previous) groups.push({ heading: c.pass || day, reason: c.reason, list: [] });
    groups[groups.length - 1].list.push(c);
    previous = key;
  }
  return (
    <BrainShell title="Changes">
      <h1 className="font-heading text-2xl font-bold text-white">What changed</h1>
      <p className="mt-1 text-sm text-muted">
        Every change to your brain, which AI made it and when. Each AI gets the same list as a catch-up when it comes
        back.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
          {error}
        </p>
      )}
      {changes?.length === 0 && <p className="mt-6 text-sm text-muted">Nothing yet.</p>}
      <div className="mt-5 space-y-6">
        {groups.map(({ heading, reason, list }, i) => (
          <section key={i}>
            <h2 className="mb-2 font-mono text-xs uppercase tracking-widest text-[#22d3ee]">{heading}</h2>
            {reason && <p className="mb-2 text-sm text-muted">{reason}</p>}
            <ul className="cb-panel divide-y divide-white/10">
              {list.map((c) => (
                <li
                  key={`${c.kind}${c.item_id}v${c.version}`}
                  className="flex flex-wrap items-baseline gap-x-2 px-4 py-2.5 text-sm"
                >
                  <b className="font-heading text-white">{who(c.by)}</b>
                  <span className="text-muted">
                    {ACTIONS[c.action] ?? c.action} {c.kind === 'memory' ? 'a memory' : 'a page'}
                  </span>
                  {c.kind === 'page' ? (
                    <Link to={`/p/${c.item_id}`} className="min-w-0 break-words text-[#c9bfff] hover:underline">
                      {c.what}
                    </Link>
                  ) : (
                    <span className="min-w-0 break-words text-charcoal">“{c.what}”</span>
                  )}
                  <span className="ml-auto text-xs text-muted">{ago(c.at)}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </BrainShell>
  );
}
