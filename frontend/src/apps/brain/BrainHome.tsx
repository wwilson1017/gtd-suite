// Common Brain — the brain itself: the memory every AI loads, the pages, and which AIs
// are connected. It refreshes every few seconds while it is on screen, so the person can
// watch an AI fill it in ("set up my brain"); what arrived since the last look glows.
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, apiErrorMessage } from '../../core/api/client';
import { CopyButton } from '../todo-gtd/components/CopyButton';
import { addMemory, createPage, getOverview, updateMemory } from './api';
import { BrainShell } from './BrainShell';
import { MoveToBrain } from './MoveToBrain';
import { HistoryDialog } from './HistoryDialog';
import type { Memory, Overview, PageSummary } from './types';
import { ago, removedNote, who } from './util';

const POLL_MS = 4000;
export const SET_UP_PROMPT = 'Set up my brain';

/** The overview, refreshed while the tab is visible; `fresh` holds what is new since the last look. */
function useOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState('');
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const known = useRef<Set<string> | null>(null);
  const load = useCallback(async () => {
    try {
      const next = await getOverview();
      const keys = [
        ...next.memories.map((m) => `m${m.id}:${m.version}`),
        ...next.pages.map((p) => `p${p.id}:${p.version}`),
      ];
      if (known.current) setFresh(new Set(keys.filter((k) => !known.current!.has(k))));
      known.current = new Set(keys);
      setData(next);
      setError('');
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not load your brain.'));
    }
  }, []);
  useEffect(() => {
    void load();
    const t = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);
  return { data, error, fresh, reload: load };
}

export function BrainHome() {
  const { data, error, fresh, reload } = useOverview();
  const busy = fresh.size > 0;
  return (
    <BrainShell live={busy}>
      {error && (
        <p role="alert" className="mb-4 text-sm text-[#ff9db0]">
          {error}
        </p>
      )}
      {data && (
        <div className="space-y-5">
          {data.nudge && <EmailNudge />}
          {(data.ais.length === 0 || data.memories.length === 0) && <SetUp first={data.ais.length === 0} />}
          {data.ais.length > 0 && <AiStrip data={data} />}
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <MemoryList data={data} fresh={fresh} reload={reload} />
            <PagesPanel data={data} fresh={fresh} />
          </div>
        </div>
      )}
      {!data && !error && <p className="text-sm text-muted">Loading your brain…</p>}
    </BrainShell>
  );
}

function EmailNudge() {
  const [hidden, setHidden] = useState(() => {
    try {
      return sessionStorage.getItem('cb-nudge') === 'no';
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  const later = () => {
    try {
      sessionStorage.setItem('cb-nudge', 'no');
    } catch {
      /* shown again next load */
    }
    setHidden(true);
  };
  return (
    <section className="cb-glow flex flex-wrap items-center gap-4 rounded-2xl p-4">
      <div className="min-w-0 flex-1">
        <h2 className="font-heading font-bold text-white">Add your email to keep growing</h2>
        <p className="mt-1 text-sm text-muted">
          Your brain can connect every AI you use and hold 2,000 memories once it has an email. It&rsquo;s still free,
          and it&rsquo;s how you sign back in on another device.
        </p>
      </div>
      <div className="flex gap-2">
        <Link to="/connect/email" className="cb-btn text-sm">
          Add my email
        </Link>
        <button type="button" onClick={later} className="cb-btn-ghost text-sm">
          Not now
        </button>
      </div>
    </section>
  );
}

function SetUp({ first }: { first: boolean }) {
  return (
    <section className="cb-panel p-5">
      <h2 className="font-heading text-lg font-bold text-white">
        {first ? 'Connect your first AI' : 'Now say “set up my brain”'}
      </h2>
      <ol className="mt-3 grid gap-3 sm:grid-cols-3">
        <li className={`rounded-xl border p-3 ${first ? 'border-[#7c5cff]' : 'border-white/10'}`}>
          <p className="font-mono text-xs tracking-widest text-[#22d3ee]">STEP 1</p>
          <p className="mt-1 font-heading font-semibold text-white">Connect your AI</p>
          <p className="mt-1 text-sm text-muted">
            ChatGPT, Claude, Grok, Gemini or a terminal agent: one link, a minute each.
          </p>
          <Link to="/connect/ai" className="cb-btn mt-3 text-sm">
            Connect an AI
          </Link>
        </li>
        <li className={`rounded-xl border p-3 ${first ? 'border-white/10' : 'border-[#7c5cff]'}`}>
          <p className="font-mono text-xs tracking-widest text-[#22d3ee]">STEP 2</p>
          <p className="mt-1 font-heading font-semibold text-white">Say “set up my brain”</p>
          <p className="mt-1 text-sm text-muted">
            It brings over what it already knows about you and asks about the gaps.
          </p>
          <div className="mt-3">
            <CopyButton text={() => SET_UP_PROMPT} label="Copy “Set up my brain”" />
          </div>
        </li>
        <li className="rounded-xl border border-white/10 p-3">
          <p className="font-mono text-xs tracking-widest text-[#22d3ee]">STEP 3</p>
          <p className="mt-1 font-heading font-semibold text-white">Watch it fill in</p>
          <p className="mt-1 text-sm text-muted">Keep this page open: each memory shows up here as your AI saves it.</p>
        </li>
      </ol>
    </section>
  );
}

function AiStrip({ data }: { data: Overview }) {
  return (
    <section aria-label="Connected AIs" className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted">Connected:</span>
      {data.ais.map((ai) => (
        <span key={ai.name} className="cb-panel flex items-center gap-1.5 rounded-full px-3 py-1">
          <span className="h-2 w-2 rounded-full bg-[#22d3ee]" aria-hidden="true" />
          <b className="font-heading text-white">{ai.name}</b>
          {/* Only when it last called: whether it ran the set-up interview is the AI's
              own business (brain_start keeps offering it), and automated jobs never do. */}
          <span className="text-xs text-muted">last used {ago(ai.last_seen_at)}</span>
        </span>
      ))}
      {data.caps.ais !== null && data.ais.length >= data.caps.ais && (
        <span className="text-xs text-muted">Add your email to connect more.</span>
      )}
    </section>
  );
}

// ── Memory ────────────────────────────────────────────────────────────────────

function MemoryList({ data, fresh, reload }: { data: Overview; fresh: Set<string>; reload: () => Promise<void> }) {
  const [text, setText] = useState('');
  const [note, setNote] = useState('');
  const [history, setHistory] = useState<number | null>(null);
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    try {
      const r = await addMemory(text.trim());
      setNote(r.memory ? removedNote(r.removed) : 'Your brain already holds that.');
      setText('');
      await reload();
    } catch (err) {
      setNote(apiErrorMessage(err, 'Could not save it.'));
    }
  };
  return (
    <section className="cb-panel p-4 sm:p-5" aria-labelledby="cb-memory">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="cb-memory" className="font-heading text-lg font-bold text-white">
          Memory
        </h2>
        <span className="text-xs text-muted">
          {data.memories.length} of {data.caps.memories} · every AI loads these first
        </span>
      </div>
      <form onSubmit={(e) => void add(e)} className="mt-3 flex gap-2">
        <input
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setNote('');
          }}
          maxLength={500}
          placeholder="Add something every AI should know…"
          aria-label="A new memory"
          className="min-w-0 flex-1 rounded-xl border border-line bg-sand px-3 py-2 text-base text-charcoal placeholder:text-muted focus:border-[#7c5cff] focus:outline-none sm:text-sm"
        />
        <button type="submit" disabled={!text.trim()} className="cb-btn text-sm">
          Add
        </button>
      </form>
      {note && (
        <p role="status" className="mt-2 text-sm text-[#ffcf9d]">
          {note}
        </p>
      )}
      {data.memories.length === 0 ? (
        <p className="mt-6 text-center text-sm text-muted">
          Nothing yet. Your AIs will add what they learn about you here.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-white/10">
          {data.memories.map((m) => (
            <MemoryRow
              key={m.id}
              m={m}
              fresh={fresh.has(`m${m.id}:${m.version}`)}
              reload={reload}
              onHistory={() => setHistory(m.id)}
            />
          ))}
        </ul>
      )}
      {history !== null && (
        <HistoryDialog kind="memory" id={history} onClose={() => setHistory(null)} onRestored={() => void reload()} />
      )}
    </section>
  );
}

function MemoryRow({
  m,
  fresh,
  reload,
  onHistory,
}: {
  m: Memory;
  fresh: boolean;
  reload: () => Promise<void>;
  onHistory: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.text);
  // The version the draft was taken from: the 4 s refresh changes `m` under this row, and a
  // save must name the version the person saw, or the server cannot catch an AI's newer edit.
  const [base, setBase] = useState(m.version);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const navigate = useNavigate();
  const edit = () => {
    setText(m.text);
    setBase(m.version);
    setError('');
    setNote('');
    setEditing(true);
  };
  const save = async (fields: Parameters<typeof updateMemory>[1], version = m.version) => {
    try {
      setNote(removedNote((await updateMemory(m.id, { ...fields, version })).removed));
      setEditing(false);
      setError('');
      await reload();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409 && 'text' in fields
          ? 'An AI changed this memory while you were editing. Your text is still here: copy it, then cancel and edit again.'
          : apiErrorMessage(e, 'Could not save it.'),
      );
    }
  };
  return (
    <li className={`group py-2.5 ${fresh ? 'cb-new rounded-lg' : ''}`}>
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save({ text }, base);
          }}
          className="flex gap-2"
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoFocus
            maxLength={500}
            aria-label="The memory"
            className="min-w-0 flex-1 rounded-lg border border-line bg-sand px-2 py-1.5 text-base text-charcoal sm:text-sm"
          />
          <button type="submit" className="cb-btn px-3 py-1.5 text-xs">
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              setEditing(false);
              setError('');
            }}
            className="cb-btn-ghost px-3 py-1.5 text-xs"
          >
            Cancel
          </button>
        </form>
      ) : (
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => void save({ locked: !m.locked })}
            aria-label={m.locked ? 'Unlock: let AIs change it' : 'Lock: no AI can change it'}
            title={m.locked ? 'Locked: no AI can change it. Unlock' : 'Lock it, so no AI can change it'}
            className={`mt-0.5 shrink-0 text-sm ${m.locked ? '' : 'opacity-30 grayscale hover:opacity-80'}`}
          >
            🔒
          </button>
          <button type="button" onClick={edit} className="min-w-0 flex-1 text-left text-sm text-charcoal">
            {m.text}
          </button>
          <span className="hidden shrink-0 text-xs text-muted sm:inline">
            {who(m.updated_by)} · {ago(m.updated_at)}
          </span>
        </div>
      )}
      <div className="mt-1 flex flex-wrap gap-x-3 pl-6 text-xs text-muted">
        <span className="sm:hidden">
          {who(m.updated_by)} · {ago(m.updated_at)}
        </span>
        <MoveToBrain kind="memory" id={m.id} version={m.version} onMoved={() => void reload()} />
        <button type="button" onClick={onHistory} className="hover:text-white">
          History
        </button>
        <button type="button" onClick={() => void save({ status: 'archived' })} className="hover:text-white">
          Archive
        </button>
        <button type="button" onClick={() => navigate(`/forget/memory/${m.id}`)} className="hover:text-[#ff9db0]">
          Forget
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-1 pl-6 text-xs text-[#ff9db0]">
          {error}
        </p>
      )}
      {note && (
        <p role="status" className="mt-1 pl-6 text-xs text-[#ffcf9d]">
          {note}
        </p>
      )}
    </li>
  );
}

// ── Pages ─────────────────────────────────────────────────────────────────────

function PagesPanel({ data, fresh }: { data: Overview; fresh: Set<string> }) {
  const [adding, setAdding] = useState(false);
  const top = (p: PageSummary) => (p.path.includes('/') ? p.path.split('/')[0] : '');
  const groups = new Map<string, PageSummary[]>();
  for (const p of data.pages) groups.set(top(p), [...(groups.get(top(p)) ?? []), p]);
  return (
    <section className="cb-panel p-4 sm:p-5" aria-labelledby="cb-pages">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="cb-pages" className="font-heading text-lg font-bold text-white">
          Pages
        </h2>
        <span className="text-xs text-muted">
          {data.pages.length} of {data.caps.pages.toLocaleString()}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">Longer things, in folders: people, projects, the daily journal.</p>
      {adding ? (
        <NewPage onDone={() => setAdding(false)} />
      ) : (
        <button type="button" onClick={() => setAdding(true)} className="cb-btn-ghost mt-3 text-sm">
          + New page
        </button>
      )}
      {data.pages.length === 0 && !adding && <p className="mt-6 text-center text-sm text-muted">No pages yet.</p>}
      <div className="mt-3 space-y-4">
        {[...groups.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([folder, list]) => (
            <div key={folder || '-'}>
              {folder && <h3 className="mb-1 font-mono text-xs uppercase tracking-widest text-[#22d3ee]">{folder}/</h3>}
              <ul className="space-y-1">
                {list.map((p) => (
                  <li key={p.id} className={fresh.has(`p${p.id}:${p.version}`) ? 'cb-new rounded-lg' : ''}>
                    <Link
                      to={`/p/${p.id}`}
                      className="flex items-baseline gap-2 rounded-lg px-2 py-1.5 hover:bg-white/5"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm text-white">{p.title}</span>
                      <span className="shrink-0 text-xs text-muted">
                        {who(p.updated_by)} · {ago(p.updated_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
      </div>
    </section>
  );
}

function NewPage({ onDone }: { onDone: () => void }) {
  const [path, setPath] = useState('');
  const [format, setFormat] = useState<'markdown' | 'html'>('markdown');
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const make = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const page = await createPage({ path, format, body: '' });
      navigate(`/p/${page.id}?edit=1`);
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not make the page.'));
    }
  };
  return (
    <form onSubmit={(e) => void make(e)} className="mt-3 space-y-2">
      <label className="block text-xs text-muted" htmlFor="cb-new-path">
        Where it goes (folders and a name)
      </label>
      <input
        id="cb-new-path"
        value={path}
        onChange={(e) => {
          setPath(e.target.value);
          setError('');
        }}
        autoFocus
        placeholder="people/maya"
        className="w-full rounded-lg border border-line bg-sand px-3 py-2 font-mono text-base text-charcoal sm:text-sm"
      />
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as 'markdown' | 'html')}
          aria-label="Format"
          className="rounded-lg border border-line bg-sand px-2 py-1.5 text-sm text-charcoal"
        >
          <option value="markdown">Markdown</option>
          <option value="html">HTML</option>
        </select>
        <button type="submit" disabled={!path.trim()} className="cb-btn px-4 py-1.5 text-sm">
          Make it
        </button>
        <button type="button" onClick={onDone} className="cb-btn-ghost text-sm">
          Cancel
        </button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-[#ff9db0]">
          {error}
        </p>
      )}
    </form>
  );
}
