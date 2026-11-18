import { brainLimitSentence } from '../../paid/features';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { useAutoSave } from '../../shared/autosave/useAutoSave';
import { InlineTitle } from '../../shared/inline-edit/InlineTitle';
import { brainName, brainGeneration, refreshBrains, selectBrain, useBrainSelection } from '../todo-gtd/brainSelection';
import { PlanCard } from '../../paid/PlanCard';
import { getBrains, saveBrain, setBrainStatus, type Brain, type BrainSettings, type BrainsView } from './api';
import { BrainShell } from './BrainShell';

// The ready-made rules: the chip's label, and the sentence the AI reads.
const PRESETS: [string, string][] = [
  ['Work only', 'Work only: no personal life, family, health or money.'],
  ['Personal only', 'Personal only: nothing about work or the company.'],
];

export const brainField = 'block w-full min-w-0 rounded-lg border border-line bg-sand px-3 py-2 text-sm text-charcoal';
export function BrainSettingsPage({ creating = false }: { creating?: boolean }) {
  const { id } = useBrainSelection();
  const [data, setData] = useState<BrainsView | null>(null);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const load = () =>
    getBrains().then(
      (d) => {
        setData(d);
        refreshBrains(d.brains);
      },
      (e) => setError(apiErrorMessage(e, 'Could not load brains.')),
    );
  useEffect(() => {
    void load();
  }, []);
  const current = data?.brains.find((b) => b.id === id);
  const full = data && data.brains.filter((b) => b.status === 'active').length >= data.caps.brains;
  const status = async (b: Brain) => {
    try {
      await setBrainStatus(b.id, b.status === 'active' ? 'archive' : 'restore');
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not change this brain.'));
    }
  };
  return (
    <BrainShell title={creating ? 'New brain' : 'Brain settings'}>
      <div className="mx-auto max-w-2xl space-y-5">
        <h1 className="font-heading text-2xl font-bold text-white">{creating ? 'New brain' : 'Brain settings'}</h1>
        {error && <p role="alert">{error}</p>}
        {!data ? (
          <p>Loading…</p>
        ) : creating && full ? (
          <>
            <p>{brainLimitSentence(data.caps.upsell)}</p>
            <PlanCard />
          </>
        ) : (
          (creating || current) && (
            <BrainForm
              key={creating ? 'new' : current!.id}
              brain={creating ? undefined : current}
              onSaved={async (b) => {
                const d = await getBrains();
                setData(d);
                refreshBrains(d.brains);
                if (creating) {
                  selectBrain(b.id);
                  navigate('/brains');
                }
              }}
            />
          )
        )}
        {!creating && current && (
          <button
            type="button"
            className="cb-btn-ghost"
            disabled={data!.brains.filter((b) => b.status === 'active').length < 2}
            onClick={() => {
              if (window.confirm(`Archive ${brainName(current)}? Its links will stop carrying it.`))
                void status(current);
            }}
          >
            Archive this brain
          </button>
        )}
        {!creating && data?.brains.some((b) => b.status === 'archived') && (
          <section className="cb-panel p-4">
            <h2 className="font-heading font-bold">Archived brains</h2>
            {data.brains
              .filter((b) => b.status === 'archived')
              .map((b) => (
                <div key={b.id} className="flex items-center gap-3 py-2">
                  <span className="min-w-0 flex-1 break-words">{brainName(b)}</span>
                  <button type="button" className="cb-btn-ghost" onClick={() => void status(b)}>
                    Restore
                  </button>
                </div>
              ))}
          </section>
        )}
      </div>
    </BrainShell>
  );
}

function BrainForm({ brain, onSaved }: { brain?: Brain; onSaved: (b: Brain) => Promise<void> }) {
  const [draft, setDraft] = useState<BrainSettings>(() => ({
    name: brain?.name ?? '',
    description: brain?.description ?? '',
    rules: brain?.rules ?? [],
    ai_access: brain?.ai_access ?? 'write',
  }));
  const draftRef = useRef(draft);
  const baseline = useRef(brain ? JSON.stringify(draft) : '');
  const saving = useAutoSave(
    async () => {
      const fields = { ...draftRef.current, rules: draftRef.current.rules.map((r) => r.trim()).filter(Boolean) };
      const snapshot = JSON.stringify(draftRef.current);
      const generation = brainGeneration();
      const b = await saveBrain(fields, brain?.id);
      if (generation !== brainGeneration()) return 'saved';
      baseline.current = snapshot;
      await onSaved(b);
      return 'saved';
    },
    () => JSON.stringify(draftRef.current) !== baseline.current,
  );
  const change = (patch: Partial<BrainSettings>) => {
    const next = { ...draftRef.current, ...patch };
    draftRef.current = next;
    setDraft(next);
    saving.syncDirty();
  };
  const rule = (i: number, text: string) =>
    change({ rules: draftRef.current.rules.map((r, j) => (i === j ? text : r)) });
  return (
    <form
      className="cb-panel space-y-4 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        saving.commit();
      }}
    >
      <label className="block text-sm">
        Name
        <input
          className={brainField}
          aria-label="Brain name"
          placeholder={brain ? brainName(brain) : 'Leave blank for an automatic name'}
          maxLength={60}
          value={draft.name}
          onChange={(e) => change({ name: e.target.value })}
          onBlur={() => {
            if (brain) saving.commit();
          }}
        />
      </label>
      {!brain && (
        <p className="text-sm text-muted">
          Leave the name blank for an automatic name, such as Brain 2. Your AI can name it once.
        </p>
      )}
      <label className="block text-sm">
        Description
        <textarea
          className={brainField}
          value={draft.description}
          onChange={(e) => change({ description: e.target.value })}
          onBlur={() => {
            if (brain) saving.commit();
          }}
        />
      </label>
      <fieldset className="min-w-0 space-y-2">
        <legend className="text-sm">Rules</legend>
        {draft.rules.map((r, i) => (
          <div key={i} className="flex min-w-0 items-center gap-2">
            <InlineTitle
              title={r}
              label={`Rule ${i + 1}`}
              placeholder="Write a rule"
              variant="body"
              onSave={async (text) => {
                rule(i, text);
                if (brain) return saving.flush();
                return true;
              }}
              className="min-w-0 flex-1 text-sm"
            />
            <button
              type="button"
              aria-label={`Remove rule ${i + 1}`}
              className="cb-btn-ghost"
              onClick={() => {
                change({ rules: draft.rules.filter((_, j) => j !== i) });
                if (brain) saving.commit();
              }}
            >
              ×
            </button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          {PRESETS.map(([label, rule]) => (
            <button
              type="button"
              key={label}
              className="cb-btn-ghost rounded-full text-sm"
              disabled={draft.rules.includes(rule)}
              onClick={() => {
                change({ rules: [...draft.rules, rule] });
                if (brain) saving.commit();
              }}
            >
              {label}
            </button>
          ))}
          <button
            type="button"
            className="cb-btn-ghost text-sm"
            onClick={() => change({ rules: [...draft.rules, ''] })}
          >
            + Add a rule
          </button>
        </div>
      </fieldset>
      <label className="block text-sm">
        AI access
        <select
          className={brainField}
          value={draft.ai_access}
          onChange={(e) => {
            change({ ai_access: e.target.value as BrainSettings['ai_access'] });
            if (brain) saving.commit();
          }}
        >
          <option value="write">AIs can write</option>
          <option value="read">AIs can only read</option>
          <option value="inbox">AIs write only into inbox</option>
        </select>
      </label>
      <button type="submit" className="cb-btn" disabled={saving.status === 'saving'}>
        {brain ? 'Save settings' : 'Create brain'}
      </button>
      <p role="status" className="text-sm text-muted">
        {saving.status === 'saved' ? 'Saved' : saving.status === 'saving' ? 'Saving…' : ''}
      </p>
      {saving.errorMessage && <p role="alert">{saving.errorMessage}</p>}
    </form>
  );
}
