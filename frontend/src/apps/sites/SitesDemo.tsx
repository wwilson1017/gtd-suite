// Simple Sites — the landing page's phone: the app's list of pages over pages held in
// this page, so a visitor watches an AI publish a small web app, uses it at its short
// address, sees an update land at the same address, and takes a page down. Nothing is
// saved or sent anywhere.
import { useState, type ReactNode } from 'react';
import { AppName } from '../todo-gtd/components/Logo';
import { DemoPhone, useToast } from '../todo-gtd/DemoPhone';

interface DemoPage {
  code: string;
  title: string;
  by: string;
  live: boolean;
  version: number;
  updated: string;
}

const field = 'mt-1 w-full rounded-lg border border-line bg-cream px-2 py-1 text-charcoal';
const step = 'rounded-lg border border-line px-2 font-heading text-charcoal';

/** The web app the AI publishes: it works, here on the page. The update adds the tip. */
function SplitBill({ tip }: { tip: boolean }) {
  const [total, setTotal] = useState('84.50');
  const [people, setPeople] = useState(3);
  const [pct, setPct] = useState(18);
  const each = ((Number(total) || 0) * (1 + (tip ? pct : 0) / 100)) / people;
  return (
    <>
      <h1>Split the bill</h1>
      <label className="mt-2 block">
        Total ($)
        <input inputMode="decimal" value={total} onChange={(e) => setTotal(e.target.value)} className={field} />
      </label>
      <div className="mt-2 flex items-center gap-2">
        People
        <button
          type="button"
          aria-label="One fewer"
          onClick={() => setPeople(Math.max(1, people - 1))}
          className={step}
        >
          −
        </button>
        <span>{people}</span>
        <button type="button" aria-label="One more" onClick={() => setPeople(people + 1)} className={step}>
          +
        </button>
      </div>
      {tip && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          Tip <mark>new</mark>
          {[15, 18, 20].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setPct(n)}
              aria-pressed={pct === n}
              className={`${step} ${pct === n ? 'border-brand-ink font-bold text-brand-ink' : ''}`}
            >
              {n}%
            </button>
          ))}
        </div>
      )}
      <p className="!mt-3 text-base">
        <b>${each.toFixed(2)}</b> each
      </p>
    </>
  );
}

/** Each page's content, by code and version: what the address shows. */
const BODIES: Record<string, ReactNode[]> = {
  'q3-Bf6Kd9Ls2W': [
    <>
      <h1>Q3 update for the board</h1>
      <p>
        Revenue <b>$412k</b>, up 18% on Q2. Two new wholesale accounts, and the second oven is running.
      </p>
      <h2>Next quarter</h2>
      <ul>
        <li>Holiday orders open October 20</li>
        <li>Hire one more baker</li>
      </ul>
    </>,
  ],
  'research-Lm4Tz9Qc7a': [
    <>
      <h1>Cold brew: who sells what</h1>
      <p>Seven cafés in town, checked October 10.</p>
      <ul>
        <li>Four sell bottles to take home</li>
        <li>Two brew it daily in-house</li>
        <li>16 oz averages $5.25</li>
      </ul>
    </>,
  ],
  'party-Wd2Nx6Hr8v': [
    <>
      <h1>Office party sign-up</h1>
      <p>Friday the 13th, from four. Add your name and a dish.</p>
    </>,
  ],
  'split-k7Qm2xPa9R': [<SplitBill tip={false} />, <SplitBill tip />],
  'trip-Hn3vW8cLq2': [
    <>
      <h1>Denver, three days</h1>
      <ol>
        <li>
          <b>Friday:</b> land 11:40, lunch on Larimer, Red Rocks at sunset
        </li>
        <li>
          <b>Saturday:</b> drive to Boulder, Chautauqua trail, dinner in town
        </li>
        <li>
          <b>Sunday:</b> farmers’ market, fly home 4:15
        </li>
      </ol>
    </>,
  ],
};

/** A report, some research, and a page taken down once it had done its job. */
const SEED: DemoPage[] = [
  {
    code: 'q3-Bf6Kd9Ls2W',
    title: 'Q3 update for the board',
    by: 'ChatGPT',
    live: true,
    version: 0,
    updated: '2 days ago',
  },
  {
    code: 'research-Lm4Tz9Qc7a',
    title: 'Cold brew: who sells what',
    by: 'Claude',
    live: true,
    version: 0,
    updated: 'last week',
  },
  {
    code: 'party-Wd2Nx6Hr8v',
    title: 'Office party sign-up',
    by: 'Claude',
    live: false,
    version: 0,
    updated: 'a month ago',
  },
];

/** What "Be the AI" does, in turn: publish a web app, update it in place, publish another. */
const AI_TURNS: { code: string; title: string; by: string; toast: string; label: string }[] = [
  {
    code: 'split-k7Qm2xPa9R',
    title: 'Split the bill',
    by: 'Claude',
    toast: 'Claude published a web app: “Split the bill”',
    label: 'publish a web app',
  },
  {
    code: 'split-k7Qm2xPa9R',
    title: 'Split the bill',
    by: 'Claude',
    toast: 'Claude added a tip: same address',
    label: 'update it',
  },
  {
    code: 'trip-Hn3vW8cLq2',
    title: 'Denver, three days',
    by: 'ChatGPT',
    toast: 'ChatGPT published “Denver, three days”',
    label: 'publish another',
  },
];

const smallBtn =
  'shrink-0 rounded-lg border border-line bg-cream px-2.5 py-1 text-xs font-heading text-charcoal hover:bg-sand';

/** ``host``: where the addresses are handed out (the short host when there is one). */
export function SitesDemo({ host = window.location.host }: { host?: string }) {
  const [pages, setPages] = useState(SEED);
  const [open, setOpen] = useState<string | null>(null);
  const [turn, setTurn] = useState(0);
  const [toast, setToast] = useToast();

  const setLive = (code: string, live: boolean) => {
    setPages((all) => all.map((p) => (p.code === code ? { ...p, live } : p)));
    setToast(live ? 'Back up, at the same address' : 'Taken down: the address shows nothing');
  };
  const aiTurn = () => {
    const step = AI_TURNS[turn % AI_TURNS.length];
    setPages((all) => {
      const had = all.find((p) => p.code === step.code);
      const page = {
        code: step.code,
        title: step.title,
        by: step.by,
        live: true,
        updated: 'just now',
        version: had ? Math.min(had.version + 1, BODIES[step.code].length - 1) : 0,
      };
      return [page, ...all.filter((p) => p.code !== step.code)];
    });
    setTurn(turn + 1);
    setOpen(step.code);
    setToast(step.toast);
  };
  const reset = () => {
    setPages(SEED);
    setOpen(null);
    setTurn(0);
    setToast('Demo reset');
  };

  const page = pages.find((p) => p.code === open);
  return (
    <DemoPhone toast={toast} aiLabel={AI_TURNS[turn % AI_TURNS.length].label} onAi={aiTurn}>
      <div className="flex items-end justify-between gap-3 px-5 pt-4">
        <div>
          <h3 className="font-heading text-xl font-bold text-charcoal">
            <AppName app="sites" />
          </h3>
          <p className="text-[13px] text-muted">A working demo. Nothing is sent anywhere.</p>
        </div>
        <button
          type="button"
          onClick={reset}
          className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:border-muted"
        >
          Reset
        </button>
      </div>
      {page ? (
        <div className="min-h-[460px] px-4 pb-6 pt-3">
          <div className="flex items-center justify-between gap-2">
            <button type="button" onClick={() => setOpen(null)} className="font-heading text-sm text-brand-ink">
              ‹ Pages
            </button>
            <button type="button" onClick={() => setLive(page.code, !page.live)} className={smallBtn}>
              {page.live ? 'Take down' : 'Put back up'}
            </button>
          </div>
          <div className="mt-3 overflow-hidden rounded-xl border border-line bg-cream shadow-sm">
            <p className="truncate border-b border-line-faint bg-sand px-3 py-1.5 text-center text-xs text-muted">
              🔒 {host}/{page.code}
            </p>
            <div className="px-4 py-4 text-sm text-charcoal [&_h1]:font-heading [&_h1]:text-xl [&_h1]:font-bold [&_h2]:mt-3 [&_h2]:font-heading [&_h2]:font-bold [&_li]:ml-5 [&_mark]:rounded [&_mark]:bg-[#f3c27a] [&_mark]:px-1 [&_ol]:mt-2 [&_ol]:list-decimal [&_p]:mt-2 [&_ul]:mt-2 [&_ul]:list-disc">
              {page.live ? (
                BODIES[page.code][page.version]
              ) : (
                <>
                  <h1>Nothing here</h1>
                  <p>This address has no page or link, or it was taken down.</p>
                </>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="min-h-[460px] px-4 pb-6 pt-3">
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-muted">Pages</h4>
          <ul className="space-y-2">
            {pages.map((p) => (
              <li key={p.code} className="rounded-xl border border-line-faint bg-cream p-3">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-heading font-bold text-charcoal">{p.title}</span>
                  <span className="text-xs text-muted">
                    {p.live ? 'Live' : 'Taken down'} · {p.by} · {p.updated}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setOpen(p.code)}
                    className="min-w-0 truncate text-left text-sm text-brand-ink underline"
                  >
                    {host}/{p.code}
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <h4 className="mb-2 mt-5 text-xs font-bold uppercase tracking-wider text-muted">Short links</h4>
          <div className="rounded-xl border border-line-faint bg-cream p-3">
            <span className="font-heading font-bold text-charcoal">Sign-up form</span>
            <p className="mt-1 truncate text-xs text-muted">
              Goes to https://forms.example.com/r/2026-volunteers-autumn
            </p>
            <p className="mt-1 text-sm text-brand-ink">{host}/form-Xb4pQ2mN8s</p>
          </div>
        </div>
      )}
    </DemoPhone>
  );
}
