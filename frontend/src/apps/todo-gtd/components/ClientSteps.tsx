import { CLIENTS } from '../clients';
import { CopyButton } from './CopyButton';

/** "Connect your AI": one disclosure per tool, each recipe carrying the list's
 *  real agent link (`url`), so it can be pasted or clicked as it stands. */
export function ClientSteps({ url }: { url: string }) {
  return (
    <div className="space-y-2">
      {CLIENTS.map((c) => (
        <details key={c.name} className="rounded-lg border border-line-faint bg-cream px-3 py-2">
          <summary className="cursor-pointer text-sm font-heading font-semibold text-charcoal">{c.name}</summary>
          <div className="mt-2 space-y-2 text-sm text-charcoal">
            {c.note && <p className="text-xs text-muted">{c.note}</p>}
            {c.deeplink && (
              <a
                href={c.deeplink(url)}
                className="inline-block rounded-lg bg-brand-dark px-3 py-1.5 text-sm font-heading text-white hover:bg-brand-deep"
              >
                Add to {c.name}
              </a>
            )}
            {c.steps && (
              <ol className="list-decimal space-y-1 pl-5">
                {c.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
            )}
            {c.steps && (
              // The chat apps take the link by hand: put it right under the steps.
              <div className="flex items-start gap-2">
                <code className="min-w-0 flex-1 select-all break-all rounded-lg border border-line bg-sand px-3 py-2 text-xs">
                  {url}
                </code>
                <CopyButton text={() => url} label={`Copy the agent link for ${c.name}`} />
              </div>
            )}
            {c.command && (
              <div>
                {c.commandLabel && <p className="mb-1 text-xs text-muted">{c.commandLabel}</p>}
                <div className="flex items-start gap-2">
                  <code className="min-w-0 flex-1 select-all break-all rounded-lg border border-line bg-sand px-3 py-2 text-xs">
                    {c.command(url)}
                  </code>
                  <CopyButton text={() => c.command!(url)} label={`Copy the ${c.name} setup`} />
                </div>
              </div>
            )}
          </div>
        </details>
      ))}
    </div>
  );
}
