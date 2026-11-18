// Notes GTD — Settings (at /connect): the way to the other apps, email, other devices,
// sign out. And Your AI (at /ai): the agent link, the same one every app shows.
import { AccountNumber, EmailSection, SignInElsewhere, ThisDevice } from '../todo-gtd/ConnectPage';
import { InstallGuide } from '../todo-gtd/components/InstallGuide';
import { OtherApps } from '../todo-gtd/components/OtherApps';
import { YourAI } from '../todo-gtd/components/YourAI';
import { PlanCard } from '../../paid/PlanCard';
import { useSession } from '../todo-gtd/session';
import { NotesShell } from './NotesShell';

export function NotesConnectPage() {
  const mail = useSession().session?.mail === true;
  return (
    <NotesShell title="Settings">
      <div className="mx-auto max-w-xl space-y-4">
        <InstallGuide />
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

export function NotesYourAIPage() {
  return (
    <NotesShell title="Your AI">
      <div className="mx-auto max-w-xl">
        <YourAI />
      </div>
    </NotesShell>
  );
}
