// Common Brain — Connect: a tab per AI with its steps and the agent link filled in, the
// words that start the set-up, the line for each AI's custom instructions, the free
// curator, the export, keys for programs; then the suite's own sections (email, plan, apps,
// devices).
import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { getAgentLink } from '../todo-gtd/api';
import { CLIENTS, type ClientSetup } from '../todo-gtd/clients';
import { AccountNumber, AgentLink, EmailSection, SignInElsewhere, ThisDevice } from '../todo-gtd/ConnectPage';
import { ClientSteps } from '../todo-gtd/components/ClientSteps';
import { CopyButton } from '../todo-gtd/components/CopyButton';
import { OtherApps } from '../todo-gtd/components/OtherApps';
import { PlanCard } from '../../paid/PlanCard';
import { useSession } from '../todo-gtd/session';
import { download, getOverview } from './api';
import { BrainShell } from './BrainShell';
import { SET_UP_PROMPT } from './BrainHome';
import { ImportMarkdown } from './ImportMarkdown';
import { MainLinkBrains } from './BrainGrants';
import { ProgramKeys } from './ProgramKeys';

/** The tabs, in the order most people need them; the rest are under More. */
const TABS: [string, string][] = [
  ['ChatGPT', 'ChatGPT'],
  ['Claude', 'Claude (claude.ai)'],
  ['Grok', 'Grok'],
  ['Gemini', 'Gemini'],
  ['Claude Code', 'Claude Code'],
  ['Codex', 'Codex'],
];
const CURATE_PROMPT = 'Tidy my brain: call brain_curate and follow it, a few items at a time.';
const code =
  'min-w-0 flex-1 select-all break-all rounded-lg border border-line bg-sand px-3 py-2 text-xs text-charcoal';

export function BrainConnectPage() {
  const [url, setUrl] = useState('');
  const [tab, setTab] = useState('ChatGPT');
  const [line, setLine] = useState('');
  const [exportSince, setExportSince] = useState('');
  const [error, setError] = useState('');
  const session = useSession().session;
  const { hash } = useLocation();
  useEffect(() => {
    getAgentLink().then(
      (l) => setUrl(l.url),
      (e) => setError(apiErrorMessage(e, 'Could not load your link.')),
    );
    getOverview().then(
      (o) => setLine(o.custom_instruction),
      () => {},
    );
  }, []);
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash, session]);
  const client = CLIENTS.find((c) => c.name === TABS.find(([t]) => t === tab)?.[1]);
  const save = (sub: string, name: string) =>
    download(sub, name).catch((e) => setError(apiErrorMessage(e, 'Could not download it.')));

  return (
    <BrainShell title="Connect">
      <div className="mx-auto max-w-2xl space-y-5">
        <section className="cb-glow rounded-2xl p-5">
          <h1 className="font-heading text-2xl font-bold text-white">Connect your AIs</h1>
          <p className="mt-1 text-sm text-muted">
            One link connects every AI to the same brain. Pick yours: its steps have your link filled in.
          </p>
          <div role="tablist" aria-label="Your AI" className="mt-4 flex flex-wrap gap-1.5">
            {[...TABS.map(([t]) => t), 'More'].map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={`rounded-full px-3 py-1.5 text-sm font-heading ${tab === t ? 'bg-[#7c5cff] text-white' : 'bg-white/5 text-muted hover:text-white'}`}
              >
                {t}
              </button>
            ))}
          </div>
          <div role="tabpanel" className="mt-4">
            {tab === 'More' ? <ClientSteps url={url} /> : client && <Steps client={client} url={url} />}
          </div>
          {error && (
            <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
              {error}
            </p>
          )}
          <div className="mt-5 rounded-xl border border-white/10 bg-white/5 p-4">
            <p className="font-heading font-semibold text-white">Then, in a new chat, say:</p>
            <div className="mt-2 flex items-start gap-2">
              <code className={`${code} text-sm`}>{SET_UP_PROMPT}</code>
              <CopyButton text={() => SET_UP_PROMPT} label="Copy “Set up my brain”" />
            </div>
            <p className="mt-2 text-xs text-muted">
              Your AI brings over what it already knows about you, asks about the gaps, and you watch your brain fill
              in. Do it once in each AI you connect.
            </p>
          </div>
        </section>

        <section className="cb-panel p-5">
          <h2 className="font-heading text-lg font-bold text-white">So every chat starts with your brain</h2>
          <p className="mt-1 text-sm text-muted">
            Set-up ends with this line. Paste it into each AI&rsquo;s custom instructions (ChatGPT: Settings →
            Personalization; Claude: Settings → personal preferences; Claude Code: CLAUDE.md; Codex: AGENTS.md).
          </p>
          <div className="mt-3 flex items-start gap-2">
            <code className={code}>{line}</code>
            <CopyButton text={() => line} label="Copy the custom instruction" />
          </div>
        </section>

        <section className="cb-panel p-5">
          <h2 className="font-heading text-lg font-bold text-white">Tidy your brain, free</h2>
          <p className="mt-1 text-sm text-muted">
            The curator runs in your own AI, never on our servers: it answers what your AIs could not find, merges
            near-copies, files the inbox and folds the week&rsquo;s journal in. Say this to any connected AI, or add the
            skill to Claude Code or Codex.
          </p>
          <div className="mt-3 flex items-start gap-2">
            <code className={code}>{CURATE_PROMPT}</code>
            <CopyButton text={() => CURATE_PROMPT} label="Copy the tidy prompt" />
          </div>
          <button
            type="button"
            onClick={() => void save('/curator-skill', 'SKILL.md')}
            className="cb-btn-ghost mt-3 text-sm"
          >
            Download the curator skill (SKILL.md)
          </button>
        </section>

        <section id="export" className="cb-panel p-5">
          <h2 className="font-heading text-lg font-bold text-white">Take it with you</h2>
          <p className="mt-1 text-sm text-muted">
            Memories, pages and history as plain files, plus a list of attachments. Download attachment files
            separately. Leave the date empty for your whole brain.
          </p>
          <label className="mt-3 block text-sm text-muted">
            Changes since (UTC)
            <input
              type="date"
              value={exportSince}
              onChange={(e) => setExportSince(e.target.value)}
              className="mt-1 block rounded-lg border border-line bg-sand px-3 py-2 text-sm text-charcoal"
            />
          </label>
          {exportSince && (
            <p className="mt-2 text-sm text-muted">Only changes after this date; this is not a full backup.</p>
          )}
          <button
            type="button"
            onClick={() =>
              void save(`/export${exportSince ? `?since=${encodeURIComponent(exportSince)}` : ''}`, 'common-brain.zip')
            }
            className="cb-btn mt-3 text-sm"
          >
            Download my brain (.zip)
          </button>
        </section>

        <ImportMarkdown />

        {session?.mail && (
          <div id="email">
            <EmailSection />
          </div>
        )}
        <AccountNumber />
        <PlanCard />
        <OtherApps />
        <details className="cb-panel p-4">
          <summary className="cursor-pointer font-heading text-sm font-semibold text-white">
            More about your agent link
          </summary>
          <div className="mt-3">
            <AgentLink />
          </div>
        </details>
        <MainLinkBrains />
        <ProgramKeys kind="link" />
        <ProgramKeys />
        <SignInElsewhere />
        <ThisDevice />
      </div>
    </BrainShell>
  );
}

function Steps({ client, url }: { client: ClientSetup; url: string }) {
  return (
    <div className="space-y-3 text-sm text-charcoal">
      {client.note && <p className="text-xs text-muted">{client.note}</p>}
      {client.steps && (
        <ol className="list-decimal space-y-1.5 pl-5">
          {client.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      )}
      {client.command ? (
        <div className="flex items-start gap-2">
          <code className={code}>{client.command(url)}</code>
          <CopyButton text={() => client.command!(url)} label={`Copy the ${client.name} setup`} />
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <code className={code}>{url}</code>
          <CopyButton text={() => url} label="Copy your agent link" />
        </div>
      )}
      <p className="text-xs text-muted">Treat the link like a key: anyone holding it can read and change your brain.</p>
    </div>
  );
}
