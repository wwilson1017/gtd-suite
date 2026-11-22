// Common Brain's Settings: the suite's sections (todo-gtd/settings/SettingsPage.tsx) and
// its own group: the brains, the words that start every chat, the free curator, import and
// export, and the other ways in (the main link's brains, staff links, program keys).
import { useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { CopyButton } from '../todo-gtd/components/CopyButton';
import { SettingsPage, type Group } from '../todo-gtd/settings/SettingsPage';
import { download, getOverview } from './api';
import { MainLinkBrains } from './BrainGrants';
import { SET_UP_PROMPT } from './BrainHome';
import { BrainShell } from './BrainShell';
import { BrainsSection } from './BrainsSection';
import { ImportMarkdown } from './ImportMarkdown';
import { ProgramKeys } from './ProgramKeys';

const CURATE_PROMPT = 'Tidy my brain: call brain_curate and follow it, a few items at a time.';
const code =
  'min-w-0 flex-1 select-all break-all rounded-lg border border-line bg-sand px-3 py-2 text-xs text-charcoal';

function EveryChat() {
  const [line, setLine] = useState('');
  useEffect(() => {
    getOverview().then(
      (o) => setLine(o.custom_instruction),
      () => {},
    );
  }, []);
  return (
    <div className="space-y-5">
      <section className="cb-glow rounded-2xl p-5">
        <h3 className="font-heading font-semibold text-white">Once an AI is connected, in a new chat, say:</h3>
        <div className="mt-2 flex items-start gap-2">
          <code className={`${code} text-sm`}>{SET_UP_PROMPT}</code>
          <CopyButton text={() => SET_UP_PROMPT} label="Copy “Set up my brain”" />
        </div>
        <p className="mt-2 text-xs text-muted">
          Your AI brings over what it already knows about you, asks about the gaps, and you watch your brain fill in. Do
          it once in each AI you connect.
        </p>
      </section>
      <section className="cb-panel p-5">
        <h3 className="font-heading font-semibold text-white">Then paste this into its custom instructions</h3>
        <p className="mt-1 text-sm text-muted">
          Set-up ends with this line. ChatGPT: Settings → Personalization; Claude: Settings → personal preferences;
          Claude Code: CLAUDE.md; Codex: AGENTS.md.
        </p>
        <div className="mt-3 flex items-start gap-2">
          <code className={code}>{line}</code>
          <CopyButton text={() => line} label="Copy the custom instruction" />
        </div>
      </section>
    </div>
  );
}

function Curator({ save }: { save: (sub: string, name: string) => void }) {
  return (
    <section className="cb-panel p-5">
      <p className="text-sm text-muted">
        The curator runs in your own AI, never on our servers: it answers what your AIs could not find, merges
        near-copies, files the inbox and folds the week&rsquo;s journal in. Say this to any connected AI, or add the
        skill to Claude Code or Codex.
      </p>
      <div className="mt-3 flex items-start gap-2">
        <code className={code}>{CURATE_PROMPT}</code>
        <CopyButton text={() => CURATE_PROMPT} label="Copy the tidy prompt" />
      </div>
      <button type="button" onClick={() => save('/curator-skill', 'SKILL.md')} className="cb-btn-ghost mt-3 text-sm">
        Download the curator skill (SKILL.md)
      </button>
    </section>
  );
}

function Export({ save }: { save: (sub: string, name: string) => void }) {
  const [since, setSince] = useState('');
  return (
    <section className="cb-panel p-5">
      <h2 className="font-heading text-lg font-bold text-white">Take it with you</h2>
      <p className="mt-1 text-sm text-muted">
        Memories, pages and history as plain files, plus a list of attachments. Download attachment files separately.
        Leave the date empty for your whole brain.
      </p>
      <label className="mt-3 block text-sm text-muted">
        Changes since (UTC)
        <input
          type="date"
          value={since}
          onChange={(e) => setSince(e.target.value)}
          className="mt-1 block rounded-lg border border-line bg-sand px-3 py-2 text-sm text-charcoal"
        />
      </label>
      {since && <p className="mt-2 text-sm text-muted">Only changes after this date; this is not a full backup.</p>}
      <button
        type="button"
        onClick={() => save(`/export${since ? `?since=${encodeURIComponent(since)}` : ''}`, 'common-brain.zip')}
        className="cb-btn mt-3 text-sm"
      >
        Download my brain (.zip)
      </button>
    </section>
  );
}

export function BrainSettings() {
  const [error, setError] = useState('');
  const save = (sub: string, name: string) =>
    void download(sub, name).catch((e) => setError(apiErrorMessage(e, 'Could not download it.')));
  const failed = error && (
    <p role="alert" className="mb-3 text-sm text-[#ff9db0]">
      {error}
    </p>
  );
  const group: Group = {
    title: 'Common Brain',
    sections: [
      {
        key: 'brains',
        icon: '◎',
        title: 'Brains',
        sub: 'Each brain’s name, rules and what AIs may do with it.',
        body: <BrainsSection />,
      },
      {
        key: 'every',
        icon: '❝',
        title: 'Every chat starts here',
        sub: 'The words that set up your brain, and one line for each AI’s custom instructions.',
        body: <EveryChat />,
      },
      {
        key: 'curator',
        icon: '✧',
        title: 'Curator',
        sub: 'Your AI tidies your brain, free.',
        body: (
          <>
            {failed}
            <Curator save={save} />
          </>
        ),
      },
      {
        // The key is the old /connect#export's, so that address still lands here.
        key: 'export',
        icon: '⇅',
        title: 'Import & export',
        sub: 'Bring Markdown in; take everything with you.',
        body: (
          <div className="space-y-5">
            <ImportMarkdown />
            {failed}
            <Export save={save} />
          </div>
        ),
      },
      {
        key: 'keys',
        icon: '⚿',
        title: 'Keys & access',
        sub: 'For people and programs that need their own way in.',
        body: (
          <div className="space-y-5">
            <MainLinkBrains />
            <ProgramKeys kind="link" />
            <ProgramKeys />
          </div>
        ),
      },
    ],
  };
  return (
    <BrainShell title="Settings">
      <SettingsPage group={group} />
    </BrainShell>
  );
}
