// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../core/api/client';
import { resetSession } from '../todo-gtd/session';
import { SitesConnectFlow } from './SitesConnectFlow';

const api = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getSession: vi.fn(),
  createList: vi.fn(),
  setEmail: vi.fn(),
  requestSignIn: vi.fn(),
  todoFetch: vi.fn(),
}));
vi.mock('../todo-gtd/api', () => api);

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const code = 'ABCD-2345';
const session = { list_id: 7, state: 'active', brains: [] };

const button = (label: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === label)!;
async function click(label: string) {
  await act(async () => {
    button(label).click();
  });
}
async function fill(selector: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(selector)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function mount(signedIn = false) {
  api.getConfig.mockResolvedValue({ signed_in: signedIn, mail: true, open_signup: true });
  await act(async () => {
    root.render(<SitesConnectFlow />);
  });
}
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks();
  resetSession();
  api.getSession.mockResolvedValue(session);
  api.setEmail.mockResolvedValue({ email: 'me@example.com', verified: false, sent: true });
  window.history.replaceState({}, '', `/connect?code=${code}`);
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  host.remove();
});

describe('SitesConnectFlow', () => {
  it('creates with the code, pins the session, saves optional email, then waits for approval', async () => {
    await mount();
    expect(host.textContent).not.toContain(code);
    expect(api.createList).not.toHaveBeenCalled();
    await fill('input[type=email]', 'me@example.com');
    await click('Create account');
    expect(api.createList).toHaveBeenCalledWith(expect.any(String), '', code);
    expect(api.getSession).toHaveBeenCalledOnce();
    expect(api.setEmail).toHaveBeenCalledWith('me@example.com');
    expect(host.textContent).not.toContain('Type the code');
    expect(host.textContent).toContain(code); // shown once this code made the account
    expect(api.todoFetch).not.toHaveBeenCalled();
    await click('Approve');
    expect(api.todoFetch).toHaveBeenCalledWith(`/connect/${code}`, { method: 'POST', body: '{}' });
    expect(host.textContent).toContain('Return to your terminal');
  });
  it('does not require email', async () => {
    await mount();
    await click('Create account');
    expect(api.setEmail).not.toHaveBeenCalled();
    expect(button('Approve')).toBeDefined();
  });
  it('can still approve after confirmation mail fails', async () => {
    await mount();
    await fill('input[type=email]', 'me@example.com');
    api.setEmail.mockRejectedValueOnce(new Error('Mail failed'));
    await click('Create account');
    expect(host.querySelector('[role=alert]')).not.toBeNull();
    await click('Approve');
    expect(host.textContent).toContain('Approved.');
  });
  it('requires a typed terminal code for an existing account and reports refusals', async () => {
    await mount(true);
    expect(host.textContent).toContain('Type the code shown in your terminal');
    expect(host.textContent).not.toContain(code); // the URL's code is never shown to an account that must type it
    expect(button('Approve').disabled).toBe(true);
    await fill('input', 'WRNG-2345');
    api.todoFetch.mockRejectedValueOnce(new ApiError(400, 'Type the code shown in your terminal', 'refused'));
    await click('Approve');
    expect(api.todoFetch).toHaveBeenCalledWith(`/connect/${code}`, {
      method: 'POST',
      body: JSON.stringify({ typed_code: 'WRNG-2345' }),
    });
    expect(host.querySelector('[role=alert]')).not.toBeNull();
    await fill('input', code);
    await click('Approve');
    expect(host.textContent).toContain('Approved.');
  });
  it('uses existing email sign-in and leaves a way back to the connection', async () => {
    await mount();
    await fill('input[type=email]', 'me@example.com');
    await click('Sign in');
    expect(api.requestSignIn).toHaveBeenCalledWith('me@example.com');
    expect(host.querySelector('a[href="/connect?code=ABCD-2345"]')).not.toBeNull();
    expect(api.todoFetch).not.toHaveBeenCalled();
  });
  it('names a Springform connection and sends its client with the approval', async () => {
    window.history.replaceState({}, '', `/connect?code=${code}&client=springform`);
    await mount();
    expect(button('Create account').disabled).toBe(true); // its free grant needs a confirmed email
    await fill('input[type=email]', 'me@example.com');
    await click('Create account');
    expect(host.textContent).toContain('Connect Springform to your GTD account');
    expect(host.textContent).toContain('A Springform install wants to use your GTD account');
    await click('Approve');
    expect(api.todoFetch).toHaveBeenCalledWith(`/connect/${code}`, {
      method: 'POST',
      body: JSON.stringify({ client: 'springform' }),
    });
    expect(host.textContent).toContain('Return to Springform');
  });
  it('lets a signed-in Springform account send its email confirmation before approving', async () => {
    window.history.replaceState({}, '', `/connect?code=${code}&client=springform`);
    await mount(true);
    await fill('input[type=email]', 'me@example.com');
    api.setEmail.mockResolvedValueOnce({ email: 'me@example.com', verified: false, sent: false });
    await click('Send confirmation link');
    expect(host.textContent).toContain('Wait a few minutes, then press Send again.');
    api.setEmail.mockResolvedValueOnce({ email: 'me@example.com', verified: false, sent: true });
    await click('Send confirmation link');
    expect(api.setEmail).toHaveBeenCalledWith('me@example.com');
    expect(host.textContent).toContain('Open the link we mailed you');
    expect(api.todoFetch).not.toHaveBeenCalled();
  });
  it('rejects a missing or malformed URL code without approving', async () => {
    window.history.replaceState({}, '', '/connect?code=bad');
    await mount();
    expect(host.querySelector('[role=alert]')?.textContent).toContain('invalid');
    expect(api.todoFetch).not.toHaveBeenCalled();
  });
});
