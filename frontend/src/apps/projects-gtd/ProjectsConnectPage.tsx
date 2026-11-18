// Projects GTD — Connect: the agent link (the same one Todo GTD shows: one link
// for every app), the way to the other apps, email, other devices, sign out.
import { AccountNumber, AgentLink, EmailSection, SignInElsewhere, ThisDevice } from '../todo-gtd/ConnectPage';
import { InstallGuide } from '../todo-gtd/components/InstallGuide';
import { OtherApps } from '../todo-gtd/components/OtherApps';
import { PlanCard } from '../../paid/PlanCard';
import { useSession } from '../todo-gtd/session';
import { ProjectsShell } from './ProjectsShell';
import { Crumbs, Perma } from './ui';

export function ProjectsConnectPage() {
  const mail = useSession().session?.mail === true;
  return (
    <ProjectsShell title="Connect">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Connect' }]} />
        <h1 className="bc-title mb-4 text-2xl">Connect</h1>
        <div className="mx-auto max-w-xl space-y-4">
          <InstallGuide />
          <AgentLink />
          <OtherApps />
          <PlanCard />
          {mail && <EmailSection />}
          <AccountNumber />
          <SignInElsewhere />
          <ThisDevice />
        </div>
      </Perma>
    </ProjectsShell>
  );
}
