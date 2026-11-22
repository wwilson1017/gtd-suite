// The optional extension's screens: off when it is not installed, so each renders nothing.
// An installed extension takes this file's place (the @extension alias in vite.config.ts)
// with the same names.
import type { AppConfig } from '../apps/todo-gtd/api';
import type { Section } from '../apps/todo-gtd/settings/setup';

export const ExtensionCard = (): null => null;
export const useExtensionSection = (): Section | null => null;
export const SitesExtra = (): null => null;
export const BrainExtra: (props: { config: AppConfig | null }) => null = () => null;
export const BrainExtraLink: (props: { config: AppConfig | null }) => null = () => null;
export const EXTRA_POLICIES: [string, string][] = [];
