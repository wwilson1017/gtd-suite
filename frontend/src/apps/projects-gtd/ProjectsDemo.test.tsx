// @vitest-environment jsdom
//
// The Projects landing page's phone: "Be the AI" adds a card, moves one to Done,
// comments and ticks a step; a visitor opens a card, ticks its checklist and moves it
// along, and adds a card; Reset puts the demo back.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { ProjectsDemo } from './ProjectsDemo';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const click = async (label: RegExp) => {
  const el = [...host.querySelectorAll('button')].find(
    (b) => label.test(b.textContent ?? '') || label.test(b.getAttribute('aria-label') ?? ''),
  );
  if (!el) throw new Error(`no ${label} in ${host.textContent}`);
  await act(async () => {
    el.click();
  });
};
/** The card titles in a column, top to bottom. */
const column = (name: string) =>
  [...host.querySelectorAll(`section[aria-label="${name}"] li button`)].map((b) =>
    b.getAttribute('aria-label')?.replace('Open card ', ''),
  );

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<ProjectsDemo />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it('the AI adds a card, moves one to Done, comments and ticks a step', async () => {
  await click(/Be the AI: add a card/);
  expect(column('To do')).toContain('Write the launch email');
  expect(host.textContent).toContain('Claude added “Write the launch email”');

  await click(/Be the AI: move a card/);
  expect(column('Done')).toContain('Homepage hero photo');
  expect(column('Doing')).not.toContain('Homepage hero photo');

  await click(/Be the AI: leave a comment/);
  await click(/Open card Write the About page/);
  expect(host.textContent).toContain('Shall I trim it');

  await click(/‹ Board/);
  await click(/Be the AI: tick a step/);
  expect(host.textContent).toContain('ChatGPT ticked “Pumpkin”');
});

it('a visitor ticks a step, moves a card along and adds one', async () => {
  await click(/Open card Shoot the seasonal cheesecakes/);
  const box = host.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  await act(async () => {
    box.click();
  });
  expect(box.checked).toBe(true);
  await click(/^Doing$/);
  expect(column('Doing')).toContain('Shoot the seasonal cheesecakes');
  expect(host.textContent).toContain('☑ 1/3');

  const input = host.querySelector<HTMLInputElement>('input[aria-label="New card in To do"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Order the boxes');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => {
    input.form!.requestSubmit();
  });
  expect(column('To do')).toContain('Order the boxes');
});

it('Reset puts the demo back', async () => {
  await click(/Be the AI/);
  await click(/Reset/);
  expect(column('To do')).not.toContain('Write the launch email');
  expect(host.textContent).toContain('Be the AI: add a card');
});
