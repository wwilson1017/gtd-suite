// @vitest-environment jsdom
//
// Focus on open: the phone capture page did not reliably put the caret in the textarea — and so
// did not raise the keyboard — when the home-screen shortcut was opened. `autoFocus` is ONE
// focus() during commit of a lazily-loaded component; nothing retried it, and nothing ran at
// all when an installed standalone app was RESUMED rather than freshly loaded.
//
// jsdom has no on-screen keyboard and no user-activation model, so what is pinned here is
// exactly the half that is ours and is observable: WHEN the component attempts focus, and when
// it must not. The keyboard itself is a platform behavior no unit test can assert — it is the
// `<!-- human-verify -->` half, confirmed on a real phone.
//
// The retries are asserted from a BLURRED start on purpose. Asserting "the textarea is focused
// after mount" would pass with the whole effect deleted, since React's own autoFocus already
// does that in jsdom; blurring first means only the deferred ladder can put focus back.
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CapturePage } from './CapturePage';

let roots: Root[] = [];

function render(node: ReactNode): Root {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => root.render(node));
  return root;
}

function unmount(root: Root) {
  act(() => root.unmount());
  roots = roots.filter((r) => r !== root);
}

function mountCapture(): Root {
  return render(<CapturePage token="SECRETTOKEN" />);
}

function textarea(): HTMLTextAreaElement {
  const el = document.querySelector('textarea');
  if (!el) throw new Error('capture textarea did not render');
  return el;
}

/** Drain the mount ladder: the rAF attempt plus both settle timeouts. */
function runLadder(): void {
  act(() => {
    vi.advanceTimersByTime(500);
  });
}

/** WebKit's non-standard standalone flag — the only home-screen signal on iOS before 16.4,
 *  and the one this suite drives (jsdom implements no matchMedia at all). */
function setIosStandalone(value: boolean): void {
  Object.defineProperty(window.navigator, 'standalone', { value, configurable: true });
}

/** Type into the textarea the way React sees it. Needed before the Send button is reachable
 *  at all — it is `disabled` while the draft is empty, and a disabled button cannot take
 *  focus, so a test that skips this silently asserts nothing about focus theft. */
function type(el: HTMLTextAreaElement, value: string): void {
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
  if (!setValue) throw new Error('no native textarea value setter');
  act(() => {
    setValue.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

/** Stand in for a touch-primary device that implements Chromium's VirtualKeyboard API.
 *  jsdom has neither `matchMedia` nor `navigator.virtualKeyboard`, so both are installed here
 *  and torn down in afterEach. Returns the `show` spy. */
function stubTouchDeviceWithVirtualKeyboard(): ReturnType<typeof vi.fn> {
  const show = vi.fn();
  Object.defineProperty(window.navigator, 'virtualKeyboard', { value: { show }, configurable: true });
  window.matchMedia = ((query: string) => ({
    matches: query === '(pointer: coarse)',
  })) as unknown as typeof window.matchMedia;
  return show;
}

beforeEach(() => {
  // rAF must be faked too, or the frame attempt never runs under fake timers.
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-09-24T17:00:00Z'));
});

afterEach(() => {
  [...roots].forEach(unmount);
  roots = [];
  vi.restoreAllMocks();
  vi.useRealTimers();
  Reflect.deleteProperty(window.navigator, 'standalone');
  Reflect.deleteProperty(window.navigator, 'virtualKeyboard');
  Reflect.deleteProperty(window, 'matchMedia');
  document.body.innerHTML = '';
});

describe('CapturePage focus-on-open', () => {
  it('re-focuses the textarea after a blur, via the deferred ladder', () => {
    mountCapture();
    const el = textarea();
    el.blur();
    expect(document.activeElement).not.toBe(el);

    runLadder();

    expect(document.activeElement).toBe(el);
  });

  it('re-focuses on a standalone resume, which is not a fresh mount', () => {
    setIosStandalone(true);
    mountCapture();
    runLadder();
    const el = textarea();
    // The OS dropped the caret while the app was backgrounded.
    el.blur();
    expect(document.activeElement).not.toBe(el);

    act(() => {
      window.dispatchEvent(new Event('pageshow'));
      vi.advanceTimersByTime(50);
    });

    expect(document.activeElement).toBe(el);
  });

  // The cold-load case the keyboard nudge exists for. React's autoFocus focuses the textarea
  // during commit, BEFORE this effect first runs, so an `already focused → return` short-circuit
  // would skip the nudge in exactly the situation it is meant to fire in.
  it('raises the virtual keyboard even when autoFocus already won the race', () => {
    const show = stubTouchDeviceWithVirtualKeyboard();
    mountCapture();
    const el = textarea();
    expect(document.activeElement).toBe(el); // autoFocus got there first

    runLadder();

    expect(show).toHaveBeenCalled();
  });

  it('does not raise the virtual keyboard on a device with a physical keyboard', () => {
    const show = vi.fn();
    Object.defineProperty(window.navigator, 'virtualKeyboard', { value: { show }, configurable: true });
    window.matchMedia = ((query: string) => ({
      matches: query !== '(pointer: coarse)',
    })) as unknown as typeof window.matchMedia;
    mountCapture();
    runLadder();

    expect(show).not.toHaveBeenCalled();
  });

  it('leaves a browser tab alone — no resume refocus outside a standalone launch', () => {
    setIosStandalone(false);
    mountCapture();
    runLadder();
    const el = textarea();
    el.blur();

    act(() => {
      window.dispatchEvent(new Event('pageshow'));
      document.dispatchEvent(new Event('visibilitychange'));
      vi.advanceTimersByTime(50);
    });

    // Desktop non-regression: switching back to the tab must not grab the caret.
    expect(document.activeElement).not.toBe(el);
  });

  it('never steals focus from another control the user is in', () => {
    setIosStandalone(true);
    mountCapture();
    runLadder();
    type(textarea(), 'a thought worth keeping');
    const send = document.querySelector('button[type="submit"]') as HTMLButtonElement;
    send.focus();
    expect(document.activeElement).toBe(send);

    act(() => {
      window.dispatchEvent(new Event('pageshow'));
      vi.advanceTimersByTime(500);
    });

    expect(document.activeElement).toBe(send);
  });

  // Asserted on the LISTENERS, not on behavior. React nulls the textarea ref on unmount, so
  // `attempt()` bails on its own `if (!el) return` whatever the cleanup did — a behavioral
  // check here stays green with both `removeEventListener` calls deleted, which is exactly
  // the leak worth catching (every later pageshow would re-arm a `requestAnimationFrame`).
  it('removes both resume listeners on unmount', () => {
    setIosStandalone(true);
    const onWindow = vi.spyOn(window, 'addEventListener');
    const onDocument = vi.spyOn(document, 'addEventListener');
    const root = mountCapture();

    const pageshowHandler = onWindow.mock.calls.find(([type]) => type === 'pageshow')?.[1];
    const visibilityHandler = onDocument.mock.calls.find(([type]) => type === 'visibilitychange')?.[1];
    expect(typeof pageshowHandler).toBe('function');
    // One handler serves both events, so the identities must match.
    expect(visibilityHandler).toBe(pageshowHandler);

    const offWindow = vi.spyOn(window, 'removeEventListener');
    const offDocument = vi.spyOn(document, 'removeEventListener');
    unmount(root);

    expect(offWindow).toHaveBeenCalledWith('pageshow', pageshowHandler);
    expect(offDocument).toHaveBeenCalledWith('visibilitychange', visibilityHandler);
  });
});

describe('CapturePage — sending', () => {
  function type(value: string) {
    const el = textarea();
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    act(() => {
      setter?.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('keeps a thought typed while the previous one is still sending', async () => {
    let answer: (r: { ok: boolean }) => void = () => {};
    const fetchMock = vi.fn(
      () =>
        new Promise<{ ok: boolean }>((resolve) => {
          answer = resolve;
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    try {
      mountCapture();
      type('first thought');
      act(() => {
        textarea().form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      type('second thought');
      await act(async () => {
        answer({ ok: true });
      });
      expect(textarea().value).toBe('second thought');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
