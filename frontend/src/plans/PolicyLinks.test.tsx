// @vitest-environment jsdom
//
// The policy pages describe the hosted service: a hosted server links them, a
// self-hosted (one-list) server does not, nor does a server whose config failed to load.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ getConfig: vi.fn() }));
vi.mock('../apps/todo-gtd/api', () => api);

import { PolicyLinks } from './PolicyLinks';

async function render(openSignup: boolean | 'fails'): Promise<string> {
  if (openSignup === 'fails') api.getConfig.mockRejectedValue(new Error('down'));
  else api.getConfig.mockResolvedValue({ open_signup: openSignup });
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  const root = createRoot(host);
  await act(async () => root.render(<PolicyLinks />));
  const text = host.textContent ?? '';
  act(() => root.unmount());
  return text;
}

it('links the policies on a hosted server and hides them on a self-hosted one', async () => {
  expect(await render(true)).toContain('Privacy');
  expect(await render(false)).toBe('');
  expect(await render('fails')).toBe('');
});
