// @vitest-environment jsdom
//
// The prices on the Brain front page are the hosted service's: a hosted server shows
// them and their menu link, a self-hosted (one-list) server shows neither, nor does a
// page still waiting for the server's answer.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import type { AppConfig } from '../apps/todo-gtd/api';
import { BrainPlans, BrainPlansLink } from './BrainPlans';

function render(config: AppConfig | null): string {
  return renderToStaticMarkup(
    <>
      <BrainPlansLink config={config} />
      <BrainPlans config={config} />
    </>,
  );
}

it('shows the prices on a hosted server and hides them on a self-hosted one', () => {
  const hosted = render({ open_signup: true } as AppConfig);
  expect(hosted).toContain('href="#pricing"');
  expect(hosted).toContain('id="pricing"');
  expect(render({ open_signup: false } as AppConfig)).toBe('');
  expect(render({ open_signup: true, free: true } as AppConfig)).toBe(''); // nothing is sold
  expect(render(null)).toBe('');
});

it('takes a link straight to the prices there once they are shown', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  const host = document.body.appendChild(document.createElement('div'));
  const root = createRoot(host);
  await act(async () => root.render(<BrainPlans config={{ open_signup: true } as AppConfig} />));
  expect(scroll).not.toHaveBeenCalled();
  act(() => root.unmount());

  history.replaceState(null, '', '/#pricing');
  const again = createRoot(host);
  await act(async () => again.render(<BrainPlans config={{ open_signup: true } as AppConfig} />));
  expect(scroll).toHaveBeenCalledTimes(1);
  expect(scroll.mock.contexts[0]).toBe(document.getElementById('pricing'));
  act(() => again.unmount());
  history.replaceState(null, '', '/');
  host.remove();
});
