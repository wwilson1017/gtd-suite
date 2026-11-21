// Todo GTD's Settings: the suite's sections (settings/SettingsPage.tsx) and its own group,
// how the app looks, the list's name and time zone, the capture link and the brain tickle.
import { MenuLayoutToggle } from '../../core/theme/MenuLayoutToggle';
import { ThemeToggle } from '../../core/theme/ThemeToggle';
import { getCaptureLink, regenerateCaptureLink } from './api';
import { BRAIN_TICKLE_PROMPT } from './clients';
import { CopyButton } from './components/CopyButton';
import { LinkCard } from './components/LinkCard';
import { ListName, TimeZone, TriageLayoutToggle } from './ConnectPage';
import { SettingsPage, type Group } from './settings/SettingsPage';
import { TodoShell } from './TodoShell';

const cardCls = 'rounded-xl border border-line-faint bg-cream p-4 sm:p-5';
const snippetCls =
  'min-w-0 flex-1 select-all whitespace-pre-wrap break-words rounded-lg border border-line bg-sand px-3 py-2 font-sans text-xs text-charcoal';

function Row({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-line-faint py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div>
        <h3 className="text-sm font-semibold text-charcoal">{title}</h3>
        <p className="mt-0.5 text-xs text-muted">{hint}</p>
      </div>
      {children}
    </div>
  );
}

/** Built when the page renders, not when the module loads: the cards name api.ts's calls. */
const todoGroup = (): Group => ({
  title: 'Todo GTD',
  sections: [
    {
      key: 'look',
      icon: '◐',
      title: 'Appearance',
      sub: 'Saved on this device.',
      body: (
        <section className={cardCls}>
          <Row title="Theme" hint="System follows this device’s light or dark setting.">
            <ThemeToggle />
          </Row>
          <Row title="Menu layout" hint="Sidebar shows on wide screens; narrower ones keep the top menu.">
            <MenuLayoutToggle />
          </Row>
          <Row
            title="Inbox triage"
            hint="Compact fits each item on one screen; Expanded adds notes, tags and people to the card."
          >
            <TriageLayoutToggle />
          </Row>
        </section>
      ),
    },
    {
      key: 'list',
      icon: '☰',
      title: 'List name & time zone',
      sub: 'Shown in the header; “today” follows the time zone.',
      body: (
        <div className="space-y-4">
          <ListName />
          <TimeZone />
        </div>
      ),
    },
    {
      key: 'capture',
      icon: '⤓',
      title: 'Capture link',
      sub: 'Add to your inbox from your phone.',
      body: (
        <LinkCard
          title="Capture link — write-only"
          accent="border-line-faint bg-cream"
          blurb={
            <>
              Adds straight to your <strong>inbox</strong>. Anyone holding it can add — but <strong>never read</strong>{' '}
              — your todos. Safe to leave on a shared home screen.
            </>
          }
          load={getCaptureLink}
          regenerate={regenerateCaptureLink}
          regenerateConfirm={
            'Make a new capture link? The old link stops working immediately — update your phone bookmark afterward.'
          }
          copyLabel="Copy the capture link"
          qrHint="Scan with your phone, then add the page to your home screen."
        />
      ),
    },
    {
      key: 'tickle',
      icon: '✧',
      title: 'Daily brain tickle',
      sub: 'One next action a day, picked by your AI.',
      body: (
        <section className={cardCls}>
          <p className="mb-3 text-sm text-muted">
            One well-chosen next action a day, with a line on why now. If your connected AI can run on a schedule, paste
            this into a scheduled task or routine.
          </p>
          <div className="flex items-start gap-2">
            <pre className={snippetCls}>{BRAIN_TICKLE_PROMPT}</pre>
            <CopyButton text={() => BRAIN_TICKLE_PROMPT} label="Copy the brain tickle instruction" />
          </div>
        </section>
      ),
    },
  ],
});

export function TodoSettings() {
  return (
    <TodoShell active="connect" hideQuickAdd>
      <SettingsPage group={todoGroup()} />
    </TodoShell>
  );
}
