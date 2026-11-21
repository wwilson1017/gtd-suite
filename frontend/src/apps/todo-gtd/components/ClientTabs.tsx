// Pick your AI: a tab for each tool most people use, with its steps and the agent link
// filled in; every other tool is under More (ClientSteps). Grok's tab leads with the one
// message to paste into a chat. In Settings › Connect your AI and on Common Brain's
// Connect page.
import { useState } from 'react';
import { APP } from '../../../core/app';
import { CLIENTS, pastePrompt, type ClientSetup } from '../clients';
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
      <div role="tablist" aria-label="Your AI tool" className="flex flex-wrap gap-1.5">
        {[...TABS.map(([t]) => t), 'More'].map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`rounded-full px-3 py-1.5 text-sm font-heading ${tab === t ? 'bg-brand-dark text-white shadow-sm' : 'bg-charcoal/5 text-muted hover:text-charcoal'}`}
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

/** Grok reads and writes from a link pasted into a chat. Common Brain's own words for that
 *  are on its page, so there the tab keeps only the connector. */
const PASTE = APP === 'brain' ? null : 'Grok';

function Steps({ client, url }: { client: ClientSetup; url: string }) {
  const paste = client.name === PASTE;
  return (
    <div className="space-y-3 text-sm text-charcoal">
      {paste && (
        <>
          <p>Paste this message into any Grok chat. That is all.</p>
          <div className="flex items-start gap-2">
            <pre className="min-w-0 flex-1 select-all whitespace-pre-wrap break-words rounded-lg border border-line bg-sand px-3 py-2 font-sans text-xs text-charcoal">
              {pastePrompt(url)}
            </pre>
            <CopyButton text={() => pastePrompt(url)} label="Copy the message for Grok" />
          </div>
          <p className="pt-1 text-xs text-muted">Or add it as a connector, on Grok&rsquo;s paid plans:</p>
        </>
      )}
      {client.note && !paste && <p className="text-xs text-muted">{client.note}</p>}
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
