import { NO_OFFERS } from '../../plans/features';
import { useEffect, useState } from 'react';
import { getConfig, type AppConfig } from './api';

/** What to assume when the server cannot be asked: offer nothing optional, and let
 *  "Start your list" try — the server refuses it (409) if the list already exists. */
const UNKNOWN: AppConfig = {
  mail: false,
  open_signup: true,
  claimed: false,
  reset: false,
  signed_in: false,
  app: 'todo',
  apps: {},
  ...NO_OFFERS,
};

// Hooks mounted together (a page and its footer's policy links) share one request.
let pending: Promise<AppConfig> | null = null;
function fetchConfig(): Promise<AppConfig> {
  pending ??= getConfig().finally(() => {
    pending = null;
  });
  return pending;
}

/** True only when the server itself answered: a failed request falls back to a guess. */
export function answered(config: AppConfig | null): config is AppConfig {
  return config !== null && config !== UNKNOWN;
}

/** What this server offers. `null` until it has answered (or failed to). */
export function useConfig(): AppConfig | null {
  const [config, setConfig] = useState<AppConfig | null>(null);
  useEffect(() => {
    let live = true;
    fetchConfig()
      .then((c) => {
        if (live) setConfig({ ...UNKNOWN, ...c });
      })
      .catch(() => {
        if (live) setConfig(UNKNOWN);
      });
    return () => {
      live = false;
    };
  }, []);
  return config;
}

/** Whether this server has another app to show beside this one (Settings › Your apps). */
export const hasOtherApps = (config: AppConfig | null) =>
  Object.keys(config?.apps ?? {}).some((key) => key !== config?.app);
