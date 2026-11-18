// @vitest-environment jsdom
//
// The Notes landing page's phone: the AI's notes show who saved them; ticking a box,
// an edit, a search and an archive work on the page's own notes; "Be the AI" saves
// a new one at the top.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { NotesDemo } from './NotesDemo';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const click = async (el: Element | null | undefined) => {
  if (!el) throw new Error(`not found in ${host.textContent}`);
  await act(async () => {
    (el as HTMLElement).click();
  });
};
const button = (label: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === label);
const card = (title: string) =>
  [...host.querySelectorAll('article')].find((a) => a.querySelector('h3')?.textContent === title)!;
const titles = () => [...host.querySelectorAll('article h3')].map((h) => h.textContent);
async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<NotesDemo />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('NotesDemo', () => {
  it('shows who saved each note, and ticking a box makes it yours', async () => {
    const trip = card('Denver trip: packing list');
    expect(trip.textContent).toContain('edited by Claude');
    const boxes = trip.querySelectorAll<HTMLInputElement>('input[type=checkbox]');
    expect([...boxes].map((b) => b.checked)).toEqual([true, false, false]);
    await click(boxes[1]);
    const after = card('Denver trip: packing list');
    expect([...after.querySelectorAll<HTMLInputElement>('input[type=checkbox]')].map((b) => b.checked)).toEqual([
      true,
      true,
      false,
    ]);
    expect(after.textContent).not.toContain('edited by');
  });

  it('edits a note in place, and its tags follow the text', async () => {
    await click(card('Call with Dana'));
    await type(host.querySelector<HTMLTextAreaElement>('textarea')!, 'Timeline sent. #done');
    await click(button('Done'));
    const dana = card('Call with Dana');
    expect(dana.textContent).toContain('Timeline sent.');
    expect(dana.textContent).toContain('#done');
    expect(dana.textContent).not.toContain('work');
  });

  it('searches every word, and archives out of sight until restored', async () => {
    await type(host.querySelector<HTMLInputElement>('input[type=search]')!, 'kitchen trim');
    expect(titles()).toEqual(['Paint colours we liked']);
    await click(
      [...card('Paint colours we liked').querySelectorAll('button')].find((b) => b.textContent === 'Archive'),
    );
    expect(titles()).toEqual([]);
    expect(host.textContent).toContain('No notes match.');
    // Nothing is deleted: the Archive brings it back.
    await type(host.querySelector<HTMLInputElement>('input[type=search]')!, '');
    await click(button('Archive (1)'));
    expect(titles()).toEqual(['Paint colours we liked']);
    await click(button('Restore'));
    await click(button('\u2190 Back to notes'));
    expect(titles()).toContain('Paint colours we liked');
  });

  it('lets the visitor be the AI: a new note lands on top, saved by the AI', async () => {
    await click(button('✦ Be the AI: save a note'));
    expect(titles()[1]).toBe('What the plumber said'); // after the pinned one
    expect(card('What the plumber said').textContent).toContain('edited by Claude · today');
    expect(host.querySelector('[role=status]')!.textContent).toBe('Claude saved “What the plumber said”');
  });
});
