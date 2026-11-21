// Projects GTD — Settings (at /connect/<section>): the suite's, in Projects' shell.
import { SettingsPage } from '../todo-gtd/settings/SettingsPage';
import { ProjectsShell } from './ProjectsShell';

export function ProjectsConnectPage() {
  return (
    <ProjectsShell title="Settings">
      <SettingsPage />
    </ProjectsShell>
  );
}
