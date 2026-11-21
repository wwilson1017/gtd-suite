// Settings › Plan: the section around PlanCard, left out where the card has nothing to show.
import { useConfig } from '../apps/todo-gtd/useConfig';
import { useSession } from '../apps/todo-gtd/session';
import type { Section } from '../apps/todo-gtd/settings/setup';
import { planShown } from './features';
import { PlanCard } from './PlanCard';

/** Settings › Plan, or null where there is no plan to show (Settings leaves it out). */
export function usePlanSection(): Section | null {
  const config = useConfig();
  const session = useSession().session;
  if (!planShown(config, session)) return null;
  const plan = session!.plan!;
  return {
    key: 'plan',
    icon: '★',
    title: 'Plan',
    sub: plan.pro
      ? `You're on ${plan.tier === 'max' ? 'Max' : 'Pro'}.`
      : config?.billing
        ? 'Free, or Pro for $36 a year.'
        : 'Your billing.',
    body: <PlanCard />,
  };
}
