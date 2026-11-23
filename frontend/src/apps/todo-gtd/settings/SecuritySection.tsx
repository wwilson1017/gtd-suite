// Settings › Security, in every app: the account's Enhanced security switch
// (backend lists.set_enhanced_security), with what it does and what it does not.
// Only the person changes it, here: no AI tool can. Below it, the read log the switch keeps
// (backend readlog.py): Common Brain reads by AI tools, for the person's eyes only.
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage } from '../../../core/api/client';
import { todoFetch } from '../api';
import { updateSession, useSession } from '../session';
import type { Session } from '../types';
import { SETTINGS } from './setup';

interface Read {
  id: number;
  at: string;
  by: string;
  kind: string;
  item_kind: 'page' | 'memory' | 'file' | null;
  target: string;
  brain: string;
  key_kind: 'key' | 'link' | null;
  key_name: string | null;
}

const PAGE = 100; // readlog.PAGE: a full page means there may be older rows

/** What a row's read was, in words. */
function what(r: Read): string {
  const item = r.item_kind === 'memory' ? 'a memory' : `${r.item_kind ?? 'page'} ${r.target}`;
  switch (r.kind) {
    case 'connect':
      return 'Connected: your locked memories';
    case 'start':
      return 'Started: the rules and memories';
    case 'search':
      return `Searched for “${r.target}”`;
    case 'list':
      return r.target ? `Listed the pages and files in ${r.target}` : 'Listed the pages and files';
    case 'get':
      return `Read ${item}`;
    case 'history':
      return `Read every version of ${item}`;
    case 'changes':
      return 'Read what changed';
    case 'link':
      return `Was given a download link to ${item}`;
    case 'export':
      return 'Downloaded an export of the brain';
    case 'curate':
      return 'Read the tidy-up queue';
    default:
      return r.kind;
  }
}

const through = (r: Read) =>
  r.key_kind === null ? 'Agent link' : `${r.key_kind === 'key' ? 'Key' : 'Staff link'}: ${r.key_name ?? 'removed'}`;

function ReadLog({ on }: { on: boolean }) {
  const [rows, setRows] = useState<Read[]>([]);
  const [older, setOlder] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(
    (before?: number) =>
      todoFetch<{ reads: Read[] }>(`/security/reads${before ? `?before=${before}` : ''}`)
        .then(({ reads }) => {
          setRows((had) => (before ? [...had, ...reads] : reads));
          setOlder(reads.length === PAGE);
          setError('');
        })
        .catch((e: unknown) => setError(apiErrorMessage(e, 'Could not load the reads. Try again.')))
        .finally(() => setLoaded(true)),
    [],
  );
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <section className="rounded-xl border border-line-faint bg-cream p-4 text-sm text-charcoal sm:p-5">
      <h3 className="font-heading text-base font-bold">Common Brain reads, last 90 days</h3>
      <p className="mt-2 text-muted">
        While Enhanced security is on, each time an AI tool reads from Common Brain a row is added here: when, which AI,
        through which link or key, and what. Only Common Brain reads are logged, not your other apps. A file row means a
        download link was handed out, not that the file was downloaded. The log is best effort: now and then a read may
        leave no row. The AI’s name is whatever the tool calls itself.
      </p>
      <p className="mt-2 text-muted">
        Rows are kept 90 days. Forgetting a page, memory or file removes its rows; the words of a search stay until they
        are 90 days old.
      </p>
      {error && (
        <p role="alert" className="mt-3">
          {error}
        </p>
      )}
      {loaded && !error && rows.length === 0 && (
        <p className="mt-3">{on ? 'No reads yet.' : 'Nothing logged. Turn on Enhanced security to start the log.'}</p>
      )}
      {rows.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3 font-normal">When</th>
                <th className="py-1 pr-3 font-normal">AI</th>
                <th className="py-1 pr-3 font-normal">Through</th>
                <th className="py-1 font-normal">What</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-line-faint align-top">
                  <td className="py-1 pr-3 whitespace-nowrap">
                    {new Date(r.at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
                  </td>
                  <td className="py-1 pr-3">{r.by}</td>
                  <td className="py-1 pr-3">{through(r)}</td>
                  <td className="py-1 break-words">
                    {what(r)}
                    {r.brain && <span className="text-muted"> · {r.brain}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {older && (
        <button type="button" className="mt-3 underline" onClick={() => void load(rows[rows.length - 1].id)}>
          Older
        </button>
      )}
    </section>
  );
}

export function SecuritySection() {
  const { session } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const toggle = async (on: boolean) => {
    setBusy(true);
    setError('');
    try {
      updateSession(
        await todoFetch<Pick<Session, 'enhanced_security' | 'agent_link_expired'>>('/security', {
          method: 'PUT',
          body: JSON.stringify({ on }),
        }),
      );
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not change Enhanced security. Try again.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line-faint bg-cream p-4 text-sm text-charcoal sm:p-5">
        <label className="font-heading text-base font-bold">
          <input
            type="checkbox"
            checked={session?.enhanced_security ?? false}
            disabled={busy || !session}
            onChange={(e) => void toggle(e.target.checked)}
          />{' '}
          Enhanced security
        </label>
        {error && (
          <p role="alert" className="mt-2">
            {error}
          </p>
        )}
        <p className="mt-3 text-muted">While it is on:</p>
        <ul className="mt-1 list-disc space-y-1.5 pl-5">
          <li>
            Your agent link stops working after 30 days without use. A new link, made under{' '}
            <Link to={`${SETTINGS}/ai`} className="underline">
              Connect your AI
            </Link>
            , starts again.
          </li>
          <li>
            A new program key or staff link needs an end date: 30, 90 or 365 days. The ones you already have keep
            working, with no end date.
          </li>
          <li>You get an email when a new AI tool first connects to your account, once a day at most.</li>
        </ul>
        {session && !session.mail ? (
          <p className="mt-3 text-muted">This server cannot send email, so it sends no alerts.</p>
        ) : (
          session &&
          !session.verified && (
            <p className="mt-3">
              <Link to={`${SETTINGS}/email`} className="font-semibold underline">
                Add your email
              </Link>{' '}
              to get the alerts: they go only to a confirmed address.
            </p>
          )
        )}
        <p className="mt-3 text-muted">
          What the email cannot catch: a tool is known by the name it gives, so one that copies the name of a tool you
          already use raises no email, and after 50 names nothing new is recorded or emailed.
        </p>
        <p className="mt-3 text-muted">
          Turning it off: an agent link that stopped for lack of use works again, and end dates already on keys and
          links still hold.
        </p>
      </section>
      <ReadLog on={session?.enhanced_security ?? false} />
    </div>
  );
}
