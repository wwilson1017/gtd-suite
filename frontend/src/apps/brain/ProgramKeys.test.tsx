// @vitest-environment jsdom
//
// Connect → For programs: a new key is shown once with a copy button, the list shows
// each key's scope and when it was last used (never the key), and revoke asks first.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ getKeys: vi.fn(), createKey: vi.fn(), revokeKey: vi.fn() }));
vi.mock('./api', () => api);
const account = vi.hoisted(() => ({ enhanced_security: false }));
vi.mock('../todo-gtd/session', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useSession: () => ({ session: account }),
}));

import { ProgramKeys } from './ProgramKeys';

const KEY = {
  id: 3,
  name: 'vm-jobs',
  last4: 'WXYZ',
  apps: 'brain' as const,
  access: 'write' as const,
  folders: ['inbox'],
  created_at: '2026-10-30T10:00:00Z',
  last_used_at: null,
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const button = (label: string) =>
  [...host.querySelectorAll('button')].find((b) => b.textContent === label) as HTMLButtonElement;
const type = (label: string, value: string) => {
  const input = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement | HTMLSelectElement;
  const proto = input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(input, value);
  input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  account.enhanced_security = false;
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

it('makes a key, shows it once, lists it without the key, and revokes it after asking', async () => {
  api.getKeys.mockResolvedValueOnce([]).mockResolvedValue([KEY]);
  api.createKey.mockResolvedValue({ ...KEY, key: 'cb_secretABCDWXYZ' });
  api.revokeKey.mockResolvedValue({ ok: true });
  await act(async () => {
    root.render(<ProgramKeys />);
  });

  await act(async () => {
    type('Key name', 'vm-jobs');
    type('Access', 'write');
    type('Folders', ' inbox , ');
  });
  expect(host.textContent).toContain('never sees a page marked confidential: true');
  await act(async () => {
    button('Make a key').click();
  });
  expect(api.createKey).toHaveBeenCalledWith({ name: 'vm-jobs', apps: 'brain', access: 'write', folders: ['inbox'] });
  expect(host.textContent).toContain('won’t be shown again');
  expect(host.textContent).toContain('cb_secretABCDWXYZ');
  const list = host.querySelector('ul')!.textContent!;
  expect(list).toContain('vm-jobs …WXYZ');
  expect(list).toContain('Common Brain · read and write · writes in inbox · never used');
  expect(list).not.toContain('cb_secret');

  vi.stubGlobal(
    'confirm',
    vi.fn(() => false),
  );
  await act(async () => {
    button('Revoke').click();
  });
  expect(api.revokeKey).not.toHaveBeenCalled();
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  );
  api.getKeys.mockResolvedValue([]);
  await act(async () => {
    button('Revoke').click();
  });
  expect(api.revokeKey).toHaveBeenCalledWith(3);
  expect(host.textContent).not.toContain('cb_secretABCDWXYZ');
});

it('gives a key an end date when asked, and always with Enhanced security on', async () => {
  api.getKeys.mockResolvedValue([
    KEY,
    { ...KEY, id: 4, name: 'dated', expires_at: '2027-01-15T12:00:00.000Z', expired: false },
    { ...KEY, id: 5, name: 'old', expires_at: '2026-01-15T12:00:00.000Z', expired: true },
  ]);
  api.createKey.mockResolvedValue({ ...KEY, key: 'cb_x' });
  await act(async () => {
    root.render(<ProgramKeys />);
  });
  const rows = [...host.querySelectorAll('li')].map((li) => li.textContent);
  expect(rows[0]).toContain('never used · no end date');
  expect(rows[1]).toContain('never used · ends Jan 15, 2027');
  expect(rows[2]).toContain('never used · expired');
  const options = () => [...host.querySelectorAll('[aria-label="End date"] option')].map((o) => o.textContent);
  expect(options()).toEqual(['No end date', 'Ends in 30 days', 'Ends in 90 days', 'Ends in 365 days']);
  await act(async () => {
    type('Key name', 'a');
    type('End date', '365');
  });
  await act(async () => {
    button('Make a key').click();
  });
  expect(api.createKey).toHaveBeenLastCalledWith({ name: 'a', apps: 'brain', access: 'read', days: 365, folders: [] });

  account.enhanced_security = true;
  await act(async () => {
    root.render(<ProgramKeys key="fresh" kind="link" />);
  });
  expect(options()).toEqual(['Ends in 30 days', 'Ends in 90 days', 'Ends in 365 days']);
  await act(async () => {
    type('Link name', 'b');
  });
  await act(async () => {
    button('Make a link').click();
  });
  expect(api.createKey).toHaveBeenLastCalledWith({
    name: 'b',
    kind: 'link',
    apps: 'brain',
    access: 'read',
    days: 90,
    folders: [],
  });
});

it('offers folders only for a Common Brain key, and sends none for every app', async () => {
  api.getKeys.mockResolvedValue([]);
  api.createKey.mockResolvedValue({ ...KEY, apps: 'all', folders: [], key: 'cb_x' });
  await act(async () => {
    root.render(<ProgramKeys />);
  });
  await act(async () => {
    type('Folders', 'inbox');
    type('Reaches', 'all');
    type('Key name', 'example');
  });
  expect(host.querySelector('[aria-label="Folders"]')).toBeNull();
  await act(async () => {
    button('Make a key').click();
  });
  expect(api.createKey).toHaveBeenCalledWith({ name: 'example', apps: 'all', access: 'read', folders: [] });
});

it('makes a named staff link with chosen brains and shows the URL only until dismissed', async () => {
  const { initializeBrains, selectBrain } = await import('../todo-gtd/brainSelection');
  initializeBrains(7, [
    { id: 11, name: 'Personal', folder: 'personal', status: 'active' },
    { id: 22, name: 'Work', folder: 'work', status: 'active' },
  ]);
  selectBrain(11);
  const link = { ...KEY, kind: 'link', brains: [22], folders: [] };
  api.getKeys.mockResolvedValueOnce([]).mockResolvedValue([link]);
  api.createKey.mockResolvedValue({ ...link, key: 'secret', link: 'https://brain.example/link/secret' });
  await act(async () => root.render(<ProgramKeys kind="link" />));
  await act(async () => {
    type('Link name', 'Curator');
    type('Access', 'write');
  });
  const ticks = host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  await act(async () => ticks[0].click());
  await act(async () => ticks[1].click());
  await act(async () => button('Make a link').click());
  expect(api.createKey).toHaveBeenCalledWith({
    name: 'Curator',
    kind: 'link',
    apps: 'brain',
    access: 'write',
    folders: [],
    brains: [22],
  });
  expect(host.textContent).toContain('https://brain.example/link/secret');
  expect(host.querySelector('ul')!.textContent).not.toContain('secret');
  await act(async () => button('Done copying').click());
  expect(host.textContent).not.toContain('https://brain.example/link/secret');
  await act(async () => root.render(<div />));
  await act(async () => root.render(<ProgramKeys kind="link" />));
  expect(host.textContent).not.toContain('https://brain.example/link/secret');
  expect(host.textContent).toContain('never used');
});

it('offers folders only while the key carries exactly one brain', async () => {
  const { initializeBrains, selectBrain } = await import('../todo-gtd/brainSelection');
  initializeBrains(8, [
    { id: 11, name: 'Personal', folder: 'personal', status: 'active' },
    { id: 22, name: 'Work', folder: 'work', status: 'active' },
  ]);
  selectBrain(11);
  api.getKeys.mockResolvedValue([]);
  await act(async () => root.render(<ProgramKeys />));
  expect(host.querySelector('[aria-label="Folders"]')).not.toBeNull();
  const ticks = host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  await act(async () => ticks[0].click());
  expect(host.querySelector('[aria-label="Folders"]')).toBeNull();
  await act(async () => ticks[1].click());
  expect(host.querySelector('[aria-label="Folders"]')).not.toBeNull();
});
