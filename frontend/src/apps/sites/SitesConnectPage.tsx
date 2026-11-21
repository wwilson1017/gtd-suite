// Simple Sites — Settings (at /connect/<section>): the suite's, in Sites' shell.
import { SettingsPage } from '../todo-gtd/settings/SettingsPage';
import { SitesShell } from './SitesShell';

export function SitesConnectPage() {
  return (
    <SitesShell title="Settings">
      <SettingsPage />
    </SitesShell>
  );
}
