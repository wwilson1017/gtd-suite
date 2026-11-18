// @vitest-environment jsdom
//
// A rendered note: ticking a box reports the offset that toggleTask needs (so the
// right line flips, nested ones included), agent-written HTML is never rendered,
// and links open with no opener.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Markdown } from './Markdown';
import { toggleTask } from './toggleTask';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('Markdown', () => {
  it('hands each box its own item offset, nested ones too', async () => {
    const body = 'Shop:\n\n- [ ] milk\n  - [x] oat\n- [ ] eggs';
    const onToggle = vi.fn<(offset: number) => void>();
    await act(async () => {
      root.render(<Markdown body={body} onToggle={onToggle} />);
    });
    const boxes = [...host.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(boxes.map((b) => b.checked)).toEqual([false, true, false]);
    await act(async () => {
      boxes[1].click();
    });
    await act(async () => {
      boxes[2].click();
    });
    const [[oat], [eggs]] = onToggle.mock.calls;
    expect(toggleTask(body, oat)).toBe('Shop:\n\n- [ ] milk\n  - [ ] oat\n- [ ] eggs');
    expect(toggleTask(body, eggs)).toBe('Shop:\n\n- [ ] milk\n  - [x] oat\n- [x] eggs');
  });

  it('skips raw HTML and opens links with no opener', async () => {
    await act(async () => {
      root.render(
        <Markdown body={'<img src=x onerror="alert(1)"> [site](https://example.com) [bad](javascript:alert(1))'} />,
      );
    });
    expect(host.querySelector('img')).toBeNull();
    const links = [...host.querySelectorAll('a')];
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer');
    expect(links[0].getAttribute('target')).toBe('_blank');
    expect(links.every((a) => !(a.getAttribute('href') ?? '').startsWith('javascript:'))).toBe(true);
  });

  it('shows a markdown image as a link and never fetches it', async () => {
    await act(async () => {
      root.render(<Markdown body="![pixel](https://tracker.example/p.gif)" />);
    });
    expect(host.querySelector('img')).toBeNull();
    const link = host.querySelector('a')!;
    expect([link.textContent, link.getAttribute('href')]).toEqual(['pixel', 'https://tracker.example/p.gif']);
  });

  it('leaves the boxes read-only without onToggle', async () => {
    await act(async () => {
      root.render(<Markdown body="- [ ] milk" />);
    });
    expect(host.querySelector<HTMLInputElement>('input[type=checkbox]')!.disabled).toBe(true);
  });
});
