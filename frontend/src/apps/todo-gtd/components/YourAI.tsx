// Your AI: the page for connecting an AI, in Todo GTD, Notes GTD and Projects GTD (each
// puts it in its own shell at /ai). Only what that takes: whether an AI has connected,
// the agent link with its copy button, and the steps for each AI. Everything else about
// the account is in Settings.
import { AgentLink } from '../ConnectPage';
import { useAiToolsOnFocus, useSession } from '../session';
import type { AiTool } from '../types';

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

export function YourAI() {
  const lines = statusLines(useSession().session?.ai_tools ?? []);
  // The person adds the link in their AI tool and comes back: the status follows, no reload.
  useAiToolsOnFocus();
  return (
    <div className="space-y-4">
      <section role="status" className="rounded-xl border border-line-faint bg-cream p-4 text-sm text-charcoal">
        {lines.length === 0 ? (
          <>
            <p className="font-heading font-semibold">No AI connected yet</p>
            <p className="mt-1 text-xs text-muted">
              Add your link to an AI below. This changes by itself the first time your AI uses it.
            </p>
          </>
        ) : (
          <ul className="space-y-1">
            {lines.map((line) => (
              <li key={line} className="flex items-start gap-2 break-words font-heading font-semibold">
                <span aria-hidden="true" className="mt-1.5 h-2 w-2 flex-none rounded-full bg-green-600" />
                <span className="min-w-0">{line}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <AgentLink tabs />
    </div>
  );
}
