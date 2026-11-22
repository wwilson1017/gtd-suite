// Simple Sites — Settings (at /connect/<section>): the suite's, in Sites' shell.
import { useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { getConfig, todoFetch } from '../todo-gtd/api';
import { updateSession, useSession } from '../todo-gtd/session';
import { SettingsPage, type Group } from '../todo-gtd/settings/SettingsPage';
import { SitesShell } from './SitesShell';

/** Own addresses: the person's switch (an AI can only suggest it). */
function OwnHost({ domain }: { domain: string }) {
  const { session } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const toggle = async (on: boolean) => {
    setBusy(true);
    setError('');
    try {
      await todoFetch('/sites/own-host', { method: 'PUT', body: JSON.stringify({ on }) });
      updateSession({ sites_own_host: on });
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not change the page addresses. Try again.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <label className="font-semibold">
        <input
          type="checkbox"
          checked={session?.sites_own_host ?? false}
          disabled={busy || !session}
          onChange={(e) => void toggle(e.target.checked)}
        />{' '}
        Own address for each page
      </label>
      <p className="mt-2 text-sm text-muted">
        Each page gets its own address (name-code.{domain}) so it can use videos and folders of files, save data in the
        browser, and embed YouTube. Off: pages stay at the shared short address, where those are blocked.
      </p>
      {error && (
        <p role="alert" className="mt-2">
          {error}
        </p>
      )}
    </div>
  );
}

export function SitesConnectPage() {
  const [domain, setDomain] = useState('');
  useEffect(() => {
    void getConfig()
      .then((config) => setDomain(config.sites_content_domain ?? ''))
      .catch(() => {});
  }, []);
  const group: Group | undefined = domain
    ? {
        title: 'Simple Sites',
        sections: [
          {
            key: 'addresses',
            icon: '⌂',
            title: 'Page addresses',
            sub: 'Where your pages live, and what they can do there.',
            body: <OwnHost domain={domain} />,
          },
        ],
      }
    : undefined;
  return (
    <SitesShell title="Settings">
      <SettingsPage group={group} />
    </SitesShell>
  );
}
