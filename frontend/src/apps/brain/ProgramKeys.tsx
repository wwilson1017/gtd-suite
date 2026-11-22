// Common Brain — Settings › Keys & access: named keys a program uses instead of the agent
// link (backend/keys.py). Make one (name, scope, access, folders), see it once, list them
// with when each was last used, revoke one.
import { useCallback, useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { CopyButton } from '../todo-gtd/components/CopyButton';
import { createKey, getKeys, revokeKey, type NewProgramKey, type ProgramKey } from './api';
import { BrainTicks } from './BrainGrants';
import { brainName, selectedBrain, useBrainSelection } from '../todo-gtd/brainSelection';
import { ago } from './util';

const field = 'rounded-lg border border-line bg-sand px-3 py-2 text-sm text-charcoal placeholder:text-muted';
const code =
  'min-w-0 flex-1 select-all break-all rounded-lg border border-line bg-sand px-3 py-2 text-xs text-charcoal';

export function ProgramKeys({ kind = 'key' }: { kind?: 'key' | 'link' }) {
  const selection = useBrainSelection();
  const link = kind === 'link';
  const noun = link ? 'link' : 'key';
  const [brains, setBrains] = useState<number[]>(() => (selectedBrain() === null ? [] : [selectedBrain()!]));
  // Folders need exactly one brain; with no brains loaded the server picks one.
  const oneBrain = selection.brains.length ? brains.length === 1 : true;
  const [busy, setBusy] = useState(false);
  const [keys, setKeys] = useState<ProgramKey[]>([]);
  const [name, setName] = useState('');
  const [apps, setApps] = useState<'brain' | 'all'>('brain');
  const [access, setAccess] = useState<'read' | 'write'>('read');
  const [folders, setFolders] = useState('');
  const [made, setMade] = useState<NewProgramKey | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(
    () =>
      getKeys().then(
        (rows) => setKeys(rows.filter((k) => (k.kind ?? 'key') === kind)),
        (e) => setError(apiErrorMessage(e, 'Could not load your keys.')),
      ),
    [kind],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const make = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setMade(null);
    setError('');
    try {
      setMade(
        await createKey({
          name,
          ...(link ? { kind } : {}),
          ...(selection.brains.length ? { brains } : {}),
          apps,
          access,
          folders:
            !link && apps === 'brain' && oneBrain
              ? folders
                  .split(',')
                  .map((f) => f.trim())
                  .filter(Boolean)
              : [],
        }),
      );
      setName('');
      setFolders('');
      void load();
    } catch (err) {
      setError(apiErrorMessage(err, `Could not make the ${noun}.`));
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (k: ProgramKey) => {
    if (!window.confirm(`Revoke ${k.name}? Anything using it stops working at once.`)) return;
    try {
      await revokeKey(k.id);
      if (made?.id === k.id) setMade(null);
      void load();
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not revoke the key.'));
    }
  };
  const curl = made && `curl -H "Authorization: Bearer ${made.key}" ${window.location.origin}/api/v1`;

  return (
    <section className="cb-panel p-5" aria-labelledby={`cb-${kind}s`}>
      <h2 id={`cb-${kind}s`} className="font-heading text-lg font-bold text-white">
        {link ? 'Named staff links' : 'For programs'}
      </h2>
      <p className="mt-1 text-sm text-muted">
        {link ? (
          'Make a separate link for each person or AI. Choose which brains it carries and whether it can write.'
        ) : (
          <>
            A script or a server uses a key instead of the agent link: on the REST API at /api/v1, or as a Bearer header
            on /mcp. Make one per program, so you can revoke it on its own. Your AIs don&rsquo;t need one.
          </>
        )}
      </p>

      <form onSubmit={(e) => void make(e)} className="mt-3 space-y-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={60}
          aria-label={link ? 'Link name' : 'Key name'}
          placeholder={link ? 'Its name, like Curator' : 'Its name, like the program: vm-jobs'}
          className={`${field} w-full`}
        />
        <div className="flex flex-wrap gap-2">
          {!link && (
            <select
              value={apps}
              onChange={(e) => setApps(e.target.value as 'brain' | 'all')}
              aria-label="Reaches"
              className={field}
            >
              <option value="brain">Common Brain only</option>
              <option value="all">Every app on this account</option>
            </select>
          )}
          <select
            value={access}
            onChange={(e) => setAccess(e.target.value as 'read' | 'write')}
            aria-label="Access"
            className={field}
          >
            <option value="read">Read only</option>
            <option value="write">Read and write</option>
          </select>
        </div>
        {!link && apps === 'brain' && oneBrain && (
          <input
            value={folders}
            onChange={(e) => setFolders(e.target.value)}
            aria-label="Folders"
            placeholder="Optional: write only in these folders, like inbox, notes/work"
            className={`${field} w-full font-mono`}
          />
        )}
        {!link && apps === 'brain' && folders.trim() && (
          <p className="text-xs text-muted">
            A key limited to folders also never sees a page marked <code>confidential: true</code>, nor the history.
          </p>
        )}
        <BrainTicks
          value={brains}
          onChange={(ids) => {
            setBrains(ids);
            if (ids.length !== 1) setFolders('');
          }}
        />
        <button type="submit" disabled={busy || !name.trim()} className="cb-btn text-sm">
          {link ? 'Make a link' : 'Make a key'}
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-2 text-sm text-[#ff9db0]">
          {error}
        </p>
      )}

      {made && (
        <div role="status" className="mt-4 rounded-xl border border-[#7c5cff]/60 bg-white/5 p-4">
          <p className="font-heading font-semibold text-white">
            Copy {made.name}&rsquo;s {noun} now: it won&rsquo;t be shown again.
          </p>
          <div className="mt-2 flex items-start gap-2">
            <code className={code}>{link ? made.link : made.key}</code>
            <CopyButton text={() => (link ? made.link! : made.key)} label={`Copy the ${noun} for ${made.name}`} />
          </div>
          <button type="button" className="cb-btn-ghost mt-2 text-xs" onClick={() => setMade(null)}>
            Done copying
          </button>
          {!link && (
            <>
              <p className="mt-3 text-xs text-muted">Try it:</p>
              <div className="mt-1 flex items-start gap-2">
                <code className={code}>{curl}</code>
                <CopyButton text={() => curl!} label="Copy the test command" />
              </div>
            </>
          )}
        </div>
      )}

      {keys.length > 0 && (
        <ul className="mt-4 divide-y divide-white/10">
          {keys.map((k) => (
            <li key={k.id} className="flex items-center gap-3 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <p className="truncate font-heading text-white">
                  {k.name} <span className="text-muted">…{k.last4}</span>
                </p>
                <p className="text-xs text-muted">
                  {k.apps === 'brain' ? 'Common Brain' : 'Every app'} ·{' '}
                  {k.access === 'read' ? 'read only' : 'read and write'}
                  {k.brains &&
                    ` · ${k.brains.map((id) => (selection.brains.find((b) => b.id === id) ? brainName(selection.brains.find((b) => b.id === id)!) : 'Archived brain')).join(', ') || 'No brains'}`}
                  {k.folders.length > 0 && ` · writes in ${k.folders.join(', ')}`}
                  {' · '}
                  {k.last_used_at ? `used ${ago(k.last_used_at)}` : 'never used'}
                </p>
              </div>
              <button type="button" onClick={() => void revoke(k)} className="cb-btn-ghost text-xs">
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
