// Projects GTD — the sample projects (backend/samples.py). Home makes them the first
// time it opens on an empty account; a loud yellow bar on every page says they are
// samples and turns them off; making a project of your own asks once more.
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { todoFetch } from '../todo-gtd/api';

export interface SampleInfo {
  /** null: never made; 'on': shown; 'off': archived. */
  state: null | 'on' | 'off';
  projects: { id: number; name: string; status: string }[];
}

// One copy for every component on the page: the bar, Home and the new-project form.
let current: SampleInfo | null = null;
let asking = false; // a project of your own was just made while the samples are on
let justOff = false; // turned off in this tab: the bar says so, and offers them back
let loading: Promise<SampleInfo> | null = null;
const listeners = new Set<() => void>();
const publish = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};

function keep(info: SampleInfo): SampleInfo {
  current = info;
  publish();
  return info;
}

function refresh(): Promise<SampleInfo> {
  loading ??= todoFetch<SampleInfo>('/projects/sample')
    .then(keep)
    .finally(() => {
      loading = null;
    });
  return loading;
}

function act(action: 'seed' | 'off' | 'on'): Promise<SampleInfo> {
  return todoFetch<SampleInfo>('/projects/sample', { method: 'POST', body: JSON.stringify({ action }) }).then(keep);
}

export function useSampleState(): SampleInfo | null {
  const info = useSyncExternalStore(subscribe, () => current);
  useEffect(() => {
    if (current === null) refresh().catch(() => {});
  }, []);
  return info;
}

/** Whether Home should ask for the samples: an account that never had them, with no project. */
export function shouldSeed(info: SampleInfo | null, projects: number | null): boolean {
  return info !== null && info.state === null && projects === 0;
}

/** Home's part: make the samples on an empty account, load again whenever they are made,
 * turned off or brought back, and ask again when Home's projects change (a sample restored
 * or archived on its own). `projects`: how many Home shows, null while loading. */
export function useSamplesOnHome(projects: number | null, reload: () => void) {
  const info = useSampleState();
  const state = info ? info.state : undefined;
  const seen = useRef(state);
  useEffect(() => {
    if (seen.current !== undefined && seen.current !== state) reload();
    seen.current = state;
  }, [state, reload]);
  useEffect(() => {
    if (projects !== null && current !== null) refresh().catch(() => {});
  }, [projects]);
  const tried = useRef(false); // once: an account with only archived projects is refused, and stays null
  useEffect(() => {
    if (tried.current || !shouldSeed(info, projects)) return;
    tried.current = true;
    act('seed').catch(() => {});
  }, [info, projects]);
}

/** Called when the person makes a project of their own: while the samples are on, the
 * bar asks whether to turn them off now. */
export function ownProjectMade() {
  if (activeSamples(current) > 0) {
    asking = true;
    publish();
  }
}

/** How many sample projects are out (not archived): the bar shows while there are any. */
export function activeSamples(info: SampleInfo | null): number {
  return info?.projects.filter((p) => p.status === 'active').length ?? 0;
}

function TurnOffDialog({
  headline,
  count,
  onDone,
}: {
  headline: string;
  count: number;
  onDone: (off: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDone(false);
    };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [onDone]);
  const off = async () => {
    setBusy(true);
    try {
      await act('off');
      onDone(true);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not turn off the sample data.'));
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={headline}
        className="w-full max-w-md rounded-2xl border-2 border-amber-400 bg-amber-50 p-6 text-amber-950 shadow-2xl"
      >
        <p className="text-xl font-extrabold">{headline}</p>
        <p className="mt-2 text-[15px]">
          This archives the {count} sample project{count === 1 ? '' : 's'}. You can restore them any time from Archived
          projects on Home. Your own projects are not touched.
        </p>
        {error && (
          <p role="alert" className="mt-2 text-sm font-semibold text-red-700">
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            autoFocus
            disabled={busy}
            onClick={() => void off()}
            className="rounded-lg bg-amber-950 px-5 py-2.5 font-bold text-amber-50 hover:bg-black disabled:opacity-60"
          >
            Turn off sample data
          </button>
          <button
            type="button"
            onClick={() => onDone(false)}
            className="rounded-lg border border-amber-400 px-4 py-2.5 font-semibold hover:bg-amber-100"
          >
            {headline.startsWith('Nice') ? 'Keep for now' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  );
}

/** The bar across the top of every page while any sample project is out. */
export function SampleBanner() {
  const info = useSampleState();
  const ask = useSyncExternalStore(subscribe, () => asking);
  const offNote = useSyncExternalStore(subscribe, () => justOff);
  const [confirming, setConfirming] = useState(false);
  const navigate = useNavigate();
  const note = (on: boolean) => {
    justOff = on;
    publish();
  };
  const count = activeSamples(info);
  const done = (off: boolean) => {
    setConfirming(false);
    asking = false;
    note(off); // each page draws its own bar, so this outlives the one that turned them off
    if (off) navigate('/');
  };
  if (count === 0 && info?.state === 'off' && offNote) {
    return (
      <div
        role="status"
        className="mb-4 flex flex-wrap items-center justify-center gap-3 rounded-xl bg-amber-100 px-4 py-2 text-[15px] text-amber-950"
      >
        <span>Sample data is off. Your projects are all yours now.</span>
        <button type="button" className="font-bold underline" onClick={() => void act('on').then(() => note(false))}>
          Bring it back
        </button>
        <button type="button" aria-label="Dismiss" className="px-1 font-bold" onClick={() => note(false)}>
          ×
        </button>
      </div>
    );
  }
  // Not only while 'on': a sample restored on its own from Archived projects is out too.
  if (count === 0) return null;
  return (
    <>
      <div
        role="region"
        aria-label="Sample data"
        className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border-2 border-amber-500 bg-amber-300 px-4 py-3 text-amber-950 sm:px-6"
      >
        <span aria-hidden className="text-4xl leading-none">
          🧪
        </span>
        <div className="min-w-[12rem] flex-1">
          <p className="text-lg font-extrabold leading-tight">You're looking at sample projects</p>
          <p className="text-[15px]">Play with them as much as you like, then turn them off to start clean.</p>
        </div>
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="rounded-lg bg-amber-950 px-5 py-2.5 text-base font-bold text-amber-50 shadow hover:bg-black"
        >
          Turn off sample data
        </button>
      </div>
      {(confirming || ask) && (
        <TurnOffDialog
          count={count}
          onDone={done}
          headline={
            confirming ? 'Turn off sample data?' : 'Nice — a project of your own. Turn off the sample data now?'
          }
        />
      )}
    </>
  );
}
