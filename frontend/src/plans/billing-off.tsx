// The selling UI is off in this build: nothing here is sold. A separate billing package
// can take this file's place (the @billing alias in vite.config.ts) with the same names.
import type { AppConfig } from '../apps/todo-gtd/api';
import type { Section } from '../apps/todo-gtd/settings/setup';

export const PlanCard = (): null => null;
export const usePlanSection = (): Section | null => null;
export const SitesPlans = (): null => null;
export const BrainPlans: (props: { config: AppConfig | null }) => null = () => null;
export const BrainPlansLink: (props: { config: AppConfig | null }) => null = () => null;
export const SOLD_POLICIES: [string, string][] = [];
