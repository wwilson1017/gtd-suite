// @vitest-environment jsdom
//
// The "Take a note…" box: closing it saves what was typed, and an empty one saves nothing.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Note } from './types';

const api = vi.hoisted(() => ({ createNote: vi.fn() }));
vi.mock('./api', () => api);

import { Composer } from './Composer';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let onCreated: ReturnType<typeof vi.fn<(note: Note) => void>>;

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  api.createNote.mockReset();
  onCreated = vi.fn<(note: Note) => void>();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<Composer onCreated={onCreated} />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const button = (name: string) => [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === name)!;

async function type(el: HTMLInputElement | HTMLTextAreaElement, text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')!.set!.call(el, text);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('Composer', () => {
  it('creates the note on close when something was typed', async () => {
    const note = { id: 1, title: 'Groceries', body: '- [ ] milk' } as Note;
    api.createNote.mockResolvedValueOnce(note);
    await act(async () => {
      button('Take a note…').click();
    });
    await type(host.querySelector('input')!, ' Groceries ');
    await type(host.querySelector('textarea')!, '- [ ] milk');
    await act(async () => {
      button('Close').click();
    });
    expect(api.createNote).toHaveBeenCalledWith({ title: 'Groceries', body: '- [ ] milk' });
    expect(onCreated).toHaveBeenCalledWith(note);
    expect(button('Take a note…')).toBeTruthy();
  });

  it('saves nothing when closed empty', async () => {
    await act(async () => {
      button('Take a note…').click();
    });
    await type(host.querySelector('textarea')!, '   ');
    await act(async () => {
      button('Close').click();
    });
    expect(api.createNote).not.toHaveBeenCalled();
    expect(button('Take a note…')).toBeTruthy();
  });

  it('locks the fields while the note is being created', async () => {
    const note = { id: 1, title: '', body: 'hi' } as Note;
    let resolve!: (n: Note) => void;
    api.createNote.mockReturnValueOnce(
      new Promise<Note>((r) => {
        resolve = r;
      }),
    );
    await act(async () => {
      button('Take a note…').click();
    });
    await type(host.querySelector('textarea')!, 'hi');
    await act(async () => {
      button('Close').click();
    });
    expect(host.querySelector('textarea')!.readOnly).toBe(true);
    expect(host.querySelector('input')!.readOnly).toBe(true);
    await act(async () => {
      resolve(note);
    });
    expect(onCreated).toHaveBeenCalledWith(note);
    expect(button('Take a note…')).toBeTruthy();
  });
});
