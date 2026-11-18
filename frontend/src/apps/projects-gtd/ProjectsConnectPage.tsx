// Projects GTD — Settings (at /connect): the way to the other apps, email, other devices,
// sign out. And Your AI (at /ai): the agent link, the same one Todo GTD shows.
import { AccountNumber, EmailSection, SignInElsewhere, ThisDevice } from '../todo-gtd/ConnectPage';
import { InstallGuide } from '../todo-gtd/components/InstallGuide';
import { OtherApps } from '../todo-gtd/components/OtherApps';
import { YourAI } from '../todo-gtd/components/YourAI';
import { PlanCard } from '../../paid/PlanCard';
import { useSession } from '../todo-gtd/session';
import { ProjectsShell } from './ProjectsShell';
import { Crumbs, Perma } from './ui';

export function ProjectsConnectPage() {
  const mail = useSession().session?.mail === true;
  return (
    <ProjectsShell title="Settings">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Settings' }]} />
        <h1 className="bc-title mb-4 text-2xl">Settings</h1>
        <div className="mx-auto max-w-xl space-y-4">
          <InstallGuide />
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

export function ProjectsYourAIPage() {
  return (
    <ProjectsShell title="Your AI">
      <Perma>
        <Crumbs crumbs={[{ label: 'Home', to: '/' }, { label: 'Your AI' }]} />
        <h1 className="bc-title mb-4 text-2xl">Your AI</h1>
        <div className="mx-auto max-w-xl">
          <YourAI />
        </div>
      </Perma>
    </ProjectsShell>
  );
}
