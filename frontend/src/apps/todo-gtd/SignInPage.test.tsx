// @vitest-environment jsdom
//
// The sign-in page: loading it redeems nothing; the button does, and goes into the
// app; a spent or expired link says so; a browser already in a list is warned that
// continuing moves it.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../core/api/client';
import type { AppConfig } from './api';
import { stubNavigation } from './stubNavigation';

const api = vi.hoisted(() => ({
  getConfig: vi.fn(),
  redeemSignIn: vi.fn(),
}));
vi.mock('./api', () => api);

import { SignInPage } from './SignInPage';

const CONFIG: AppConfig = {
  mail: true,
  open_signup: true,
  claimed: false,
  reset: false,
  signed_in: false,
  app: 'todo',
  apps: {},
};
const WARNING = 'This browser is signed in to a list already. Continuing signs it out of that one here, in every tab.';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let nav: ReturnType<typeof stubNavigation>;

async function mount(config: AppConfig = CONFIG): Promise<void> {
  api.getConfig.mockResolvedValue(config);
  await act(async () => {
    root.render(<SignInPage token="TOKEN" />);
  });
}

const button = () => [...host.querySelectorAll('button')].find((b) => b.textContent === 'Open my list on this device')!;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  nav = stubNavigation();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  host.remove();
  vi.unstubAllGlobals();
});

describe('SignInPage', () => {
  it('redeems nothing on load, then signs this browser in on the button and opens the app', async () => {
    api.redeemSignIn.mockResolvedValue({ verified: false });
    await mount();
    expect(api.redeemSignIn).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain(WARNING);
    await act(async () => {
      button().click();
    });
    expect(api.redeemSignIn).toHaveBeenCalledWith('TOKEN');
    expect(nav.replace).toHaveBeenCalledWith('/app');
  });

  it('says a spent or expired link is no good, and stays put', async () => {
    api.redeemSignIn.mockRejectedValue(new ApiError(404, 'Not found', 'x'));
    await mount();
    await act(async () => {
      button().click();
    });
    expect(host.querySelector('[role="alert"]')!.textContent).toContain('works once, for one hour');
    expect(nav.replace).not.toHaveBeenCalled();
    expect(button().disabled).toBe(false);
  });

  it('warns a browser that is already in a list that continuing moves it, in every tab', async () => {
    await mount({ ...CONFIG, signed_in: true });
    expect(host.textContent).toContain(WARNING);
  });
});
