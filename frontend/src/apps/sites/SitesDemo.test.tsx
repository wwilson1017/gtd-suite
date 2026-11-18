// @vitest-environment jsdom
//
// The Sites landing page's phone: "Be the AI" publishes a small web app that works and
// opens it at its short address, then updates it at the same address; a page taken
// down shows nothing there and comes back; Reset puts the demo back.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { SitesDemo } from './SitesDemo';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const click = async (label: RegExp) => {
  const el = [...host.querySelectorAll('button')].find((b) => label.test(b.textContent ?? ''));
  if (!el) throw new Error(`no ${label} in ${host.textContent}`);
  await act(async () => {
    el.click();
  });
};
const address = () => [...host.querySelectorAll('p')].find((p) => p.textContent?.includes('🔒'))?.textContent;

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<SitesDemo />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it('publishes a web app that works, and updates it at the same address', async () => {
  expect(host.textContent).toContain('Q3 update for the board');
  expect(host.textContent).toContain('Taken down · Claude'); // the party page, once it was over
  await click(/Be the AI: publish a web app/);
  expect(address()).toContain('/split-k7Qm2xPa9R');
  expect(host.textContent).toContain('Claude published a web app: “Split the bill”');
  expect(host.textContent).toContain('$28.17 each'); // 84.50 for 3
  await click(/^\+$/);
  expect(host.textContent).toContain('$21.13 each'); // for 4
  expect(host.textContent).not.toContain('Tip');

  await click(/Be the AI: update it/);
  expect(address()).toContain('/split-k7Qm2xPa9R');
  expect(host.textContent).toContain('$24.93 each'); // 18% tip, still 4 people
  await click(/^20%$/);
  expect(host.textContent).toContain('$25.35 each');

  await click(/Pages/);
  const rows = [...host.querySelectorAll('li')].map((li) => li.querySelector('span')?.textContent);
  expect(rows).toEqual([
    'Split the bill',
    'Q3 update for the board',
    'Cold brew: who sells what',
    'Office party sign-up',
  ]);
});

it('a page taken down shows nothing at its address, and comes back', async () => {
  await click(/q3-Bf6Kd9Ls2W/);
  await click(/Take down/);
  expect(host.textContent).toContain('Nothing here');
  await click(/Put back up/);
  expect(host.textContent).toContain('Revenue');
});

it('Reset puts the demo back', async () => {
  await click(/Be the AI/);
  await click(/Reset/);
  expect(host.textContent).not.toContain('Split the bill');
  expect(host.textContent).toContain('Be the AI: publish a web app');
});

it('shows its addresses on the host it is given', async () => {
  await act(async () => {
    root.render(<SitesDemo host="ss.page" />);
  });
  await click(/Be the AI: publish a web app/);
  expect(address()).toContain('ss.page/split-k7Qm2xPa9R');
});
