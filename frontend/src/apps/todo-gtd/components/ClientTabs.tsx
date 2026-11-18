// Pick your AI: a tab for each tool most people use, with its steps and the agent link
// filled in; every other tool is under More (ClientSteps). On Your AI and on Common
// Brain's Connect page.
import { useState } from 'react';
import { CLIENTS, type ClientSetup } from '../clients';
import { ClientSteps } from './ClientSteps';
import { CopyButton } from './CopyButton';

/** The tabs, in the order most people need them: the label, and the tool's name in CLIENTS. */
const TABS: [string, string][] = [
  ['ChatGPT', 'ChatGPT'],
  ['Claude', 'Claude (claude.ai)'],
  ['Grok', 'Grok'],
  ['Gemini', 'Gemini'],
  ['Claude Code', 'Claude Code'],
  ['Codex', 'Codex'],
];
const code =
  'min-w-0 flex-1 select-all break-all rounded-lg border border-line bg-sand px-3 py-2 text-xs text-charcoal';

export function ClientTabs({ url }: { url: string }) {
  const [tab, setTab] = useState(TABS[0][0]);
  const client = CLIENTS.find((c) => c.name === TABS.find(([t]) => t === tab)?.[1]);
  return (
    <>
      <div role="tablist" aria-label="Your AI" className="flex flex-wrap gap-1.5">
        {[...TABS.map(([t]) => t), 'More'].map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`rounded-full px-3 py-1.5 text-sm font-heading ${tab === t ? 'bg-brand-dark text-white' : 'bg-charcoal/5 text-muted hover:text-charcoal'}`}
          >
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="mt-4">
        {tab === 'More' ? <ClientSteps url={url} /> : client && <Steps client={client} url={url} />}
      </div>
    </>
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
    </div>
  );
}
