// Notes GTD — Settings (at /connect/<section>): the suite's, in Notes' shell.
import { SettingsPage } from '../todo-gtd/settings/SettingsPage';
import { NotesShell } from './NotesShell';

export function NotesConnectPage() {
  return (
    <NotesShell title="Settings">
      <SettingsPage />
    </NotesShell>
  );
}
