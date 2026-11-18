// @vitest-environment jsdom
//
// The editor's version check: a save that an agent's edit beat comes back 409, the
// draft stays, a banner says who changed it, and "Keep mine" saves the draft again
// over the version the server holds now.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../core/api/client';
import type { Note } from './types';

const api = vi.hoisted(() => ({ getNote: vi.fn(), updateNote: vi.fn() }));
vi.mock('./api', () => api);

import { NoteEditor } from './NoteEditor';

const NOTE: Note = {
  id: 3,
  title: 'Trip',
  body: 'Pack',
  tags: [],
  color: '',
  pinned: false,
  status: 'active',
  version: 1,
  source: 'ui',
  source_client: null,
  edited_by: null,
  created_at: '2026-10-12T00:00:00Z',
  updated_at: '2026-10-12T00:00:00Z',
};
const THEIRS: Note = { ...NOTE, body: 'Pack the tent', version: 4, edited_by: 'Claude' };

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let onClose: ReturnType<typeof vi.fn<() => void>>;

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  api.getNote.mockReset();
  api.updateNote.mockReset();
  onClose = vi.fn<() => void>();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<NoteEditor note={NOTE} onClose={onClose} onChanged={() => {}} />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const body = () => host.querySelector('textarea')!;
const button = (name: string) => [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === name);

async function editBody(text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(body(), text);
    body().dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => {
    body().dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
  });
}

describe('NoteEditor conflicts', () => {
  it('keeps the draft on a 409, names who changed it, and Keep mine saves over their version', async () => {
    api.updateNote.mockRejectedValueOnce(new ApiError(409, 'changed', 'API error 409: changed'));
    api.getNote.mockResolvedValueOnce(THEIRS);
    await editBody('Pack light');
    expect(api.updateNote).toHaveBeenCalledWith(3, { body: 'Pack light', version: 1 });
    expect(host.querySelector('[role=alert]')?.textContent).toContain('Changed by Claude while you were editing');
    expect(body().value).toBe('Pack light');

    // Nothing more is written until the person picks.
    await act(async () => {
      body().dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    });
    expect(api.updateNote).toHaveBeenCalledTimes(1);

    api.updateNote.mockResolvedValueOnce({ ...THEIRS, body: 'Pack light', version: 5, edited_by: null });
    await act(async () => {
      button('Keep mine')!.click();
    });
    expect(api.updateNote).toHaveBeenLastCalledWith(3, { body: 'Pack light', version: 4 });
    expect(button('Keep mine')).toBeUndefined();
  });

  it('Use theirs shows their text and drops the draft', async () => {
    api.updateNote.mockRejectedValueOnce(new ApiError(409, 'changed', 'API error 409: changed'));
    api.getNote.mockResolvedValueOnce(THEIRS);
    await editBody('Pack light');
    await act(async () => {
      button('Use theirs')!.click();
    });
    expect(body().value).toBe('Pack the tent');
    await act(async () => {
      host.querySelector<HTMLButtonElement>('[aria-label=Close]')!.click();
    });
    expect(api.updateNote).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });

  describe('NoteEditor leaving without close', () => {
    it('saves typing that has not paused yet when unmounted (browser Back)', async () => {
      api.updateNote.mockResolvedValueOnce({ ...NOTE, body: 'Pack light', version: 2 });
      await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(body(), 'Pack light');
        body().dispatchEvent(new Event('input', { bubbles: true }));
      });
      expect(api.updateNote).not.toHaveBeenCalled();
      await act(async () => {
        root.unmount();
      });
      expect(api.updateNote).toHaveBeenCalledWith(3, { body: 'Pack light', version: 1 });
    });

    it('sends nothing when an unchanged editor unmounts', async () => {
      await act(async () => {
        root.unmount();
      });
      expect(api.updateNote).not.toHaveBeenCalled();
    });
  });
});
