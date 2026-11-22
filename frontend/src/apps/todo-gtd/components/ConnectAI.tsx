// Settings › Connect your AI, in every app: whether an AI has connected
// (a line per tool, or waiting), the steps for each AI with the agent link filled in, and
// the agent link itself with a quiet way to make a new one.
import { useState } from 'react';
import { getAgentLink, regenerateAgentLink } from '../api';
import { useAiToolsOnFocus, useSession } from '../session';
import type { AiTool } from '../types';
import { ClientTabs } from './ClientTabs';
import { ConnectAnimation } from './ConnectAnimation';
import { LinkCard } from './LinkCard';

/** "today", "yesterday" or a date: the server records a call to the hour at best, so the
 *  page says a day and never a time. */
function lastUsed(tool: AiTool): string {
  if (tool.days_ago === 0) return 'today';
  if (tool.days_ago === 1) return 'yesterday';
  // From its parts: new Date('YYYY-MM-DD') is UTC midnight, the day before west of Greenwich.
  const [y, m, d] = (tool.last_used ?? '').split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** The status, a line per tool: "Claude connected · last used today". The latest three
 *  callers get a line each and the rest share one. A name is the tool's own claim, so it
 *  is only ever shown as text. */
function statusLines(tools: AiTool[]): string[] {
  // A tool that names itself only when it first connects also leaves an unnamed row: not a second tool.
  const named = tools.filter((t) => t.name);
  const shown = named.length ? named : tools.slice(0, 1);
  const lines = shown
    .slice(0, 3)
    .map((t) => `${t.name || 'An AI tool'} connected${t.last_used ? ` · last used ${lastUsed(t)}` : ''}`);
  const rest = shown.slice(3).map((t) => t.name);
  return rest.length ? [...lines, `Also connected: ${new Intl.ListFormat('en').format(rest)}`] : lines;
}

export function ConnectAI() {
  const lines = statusLines(useSession().session?.ai_tools ?? []);
  const [url, setUrl] = useState('');
  // The person adds the link in their AI tool and comes back: the status follows, no reload.
  useAiToolsOnFocus();
  return (
    <div className="space-y-4">
      {lines.length === 0 ? (
        <p
          role="status"
          className="flex items-center gap-2.5 rounded-xl border border-dashed border-line bg-sand px-4 py-3 font-heading text-sm font-semibold text-charcoal"
        >
          <span aria-hidden="true" className="h-2.5 w-2.5 flex-none animate-pulse rounded-full bg-muted" />
          Waiting for your AI. This turns green the first time it uses your link.
        </p>
      ) : (
        <ul role="status" className="space-y-1.5">
          {lines.map((line) => (
            <li
              key={line}
              className="flex items-start gap-2.5 break-words rounded-xl bg-green-50 px-4 py-3 font-heading text-sm font-semibold text-green-800 dark:bg-green-950/50 dark:text-green-300"
            >
              <span aria-hidden="true" className="mt-1.5 h-2.5 w-2.5 flex-none rounded-full bg-current" />
              <span className="min-w-0">{line}</span>
            </li>
          ))}
        </ul>
      )}
      <section className="rounded-xl border border-line-faint bg-cream p-4 sm:p-5">
        <h2 className="mb-3 font-heading text-base font-bold text-charcoal">
          {lines.length ? 'Add another AI' : 'Pick your AI'}
        </h2>
        {url && <ClientTabs url={url} />}
        <ConnectAnimation />
      </section>
      <LinkCard
        title="Your agent link"
        accent="border-line-faint bg-cream"
        blurb={
          <>
            One link for every app. Treat it like a key: anyone holding it can do what your AI can. It cannot delete
            anything, or see the links in Settings. Open it in a browser to see what it offers.
          </>
        }
        load={getAgentLink}
        regenerate={regenerateAgentLink}
        regenerateConfirm={
          'Make a new agent link?\n\nThe old link stops working immediately, and every AI ' +
          'tool you connected with it must be re-added with the new one. Your capture link is ' +
          'not affected, and every signed-in device stays signed in.'
        }
        copyLabel="Copy the agent link"
        onUrl={setUrl}
      />
    </div>
  );
}
