// Notes GTD — Connect: the agent link (the same one every app shows: one link for
// every app), the way to the other apps, email, other devices, sign out.
import { AccountNumber, AgentLink, EmailSection, SignInElsewhere, ThisDevice } from '../todo-gtd/ConnectPage';
import { InstallGuide } from '../todo-gtd/components/InstallGuide';
import { OtherApps } from '../todo-gtd/components/OtherApps';
import { PlanCard } from '../../paid/PlanCard';
import { useSession } from '../todo-gtd/session';
import { NotesShell } from './NotesShell';

export function NotesConnectPage() {
  const mail = useSession().session?.mail === true;
  return (
    <NotesShell title="Connect">
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
    </NotesShell>
  );
}
