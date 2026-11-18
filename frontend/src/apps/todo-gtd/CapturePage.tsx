// Todo GTD — the PUBLIC capture page.
//
// Reached at /c/:token by whoever holds the list's capture link — typically the
// owner's phone home-screen bookmark. No login, no account. Write-only by
// design: this page can add to the inbox but can never read it, so a leaked
// bookmark exposes nothing.

import { useEffect, useRef, useState } from 'react';
import { BASE, APP_TITLE } from '../../core/app';
import { Logo } from './components/Logo';

type Status = { kind: 'idle' } | { kind: 'sending' } | { kind: 'captured' } | { kind: 'error'; message: string };

/** One `matchMedia` probe that survives an environment without it (jsdom, old WebViews). */
function mediaMatches(query: string): boolean {
  return window.matchMedia?.(query).matches === true;
}

/** Is this the installed, chrome-less app rather than a browser tab?
 *
 * Two signals because neither covers both platforms: `navigator.standalone` is WebKit's
 * non-standard flag and the ONLY signal on iOS before 16.4, while `(display-mode: standalone)`
 * is the standard one Chromium and modern iOS answer. The focus fallback is needed on home-screen launches;
 * gating the resume handler on them keeps a desktop browser
 * tab from grabbing the caret every time the user switches back to it.
 */
function isStandaloneLaunch(): boolean {
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone || mediaMatches('(display-mode: standalone)');
}

/** Ask Chromium to raise the on-screen keyboard for the already-focused textarea.
 *
 * The VirtualKeyboard API is the one lever that can show the keyboard for a form control the
 * script focused rather than the user tapped; its documented precondition is exactly that — a
 * focused form control, which `<textarea>` is. Strictly BEST-EFFORT: WebKit and Gecko do not
 * implement it (so it does nothing for the iPhone this was reported on), and Chromium may
 * still refuse it without user activation. Feature-detected and wrapped so a refusal is a
 * silent no-op and never an error on a page whose whole job is to accept one line of text.
 *
 * `navigator.virtualKeyboard.overlaysContent` is deliberately NOT set: that opts the page into
 * owning the keyboard's layout geometry, which would change how this textarea sits on screen.
 * We want the keyboard, not the layout contract.
 */
function nudgeVirtualKeyboard(): void {
  const vk = (navigator as Navigator & { virtualKeyboard?: { show?: () => void } }).virtualKeyboard;
  try {
    vk?.show?.();
  } catch {
    // Unsupported or refused — the full-width textarea is the tap fallback.
  }
}

function messageFor(status: number, body: unknown): string {
  if (status === 404)
    return 'This capture link was not found. It may have been regenerated — open your list and copy the new one from ⚙ Connect.';
  const detail = (body as { detail?: unknown } | null)?.detail;
  // The server's own words first: its 429 is a plain string with a 60s window, so the
  // "about 5 seconds" guess below would send the user straight back into the limit.
  if (typeof detail === 'string') return detail;
  if (status === 429 || status === 503) {
    const wait = (detail as { retry_after?: number } | null)?.retry_after ?? 5;
    return `Busy right now — try again in about ${wait} second${wait === 1 ? '' : 's'}.`;
  }
  return `Failed (${status}) — try again.`;
}

export function CapturePage({ token }: { token: string }) {
  const [text, setText] = useState('');
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const clearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (clearTimer.current) clearTimeout(clearTimer.current);
    },
    [],
  );

  // ── Keyboard on open ───────────────────────────────────────────────────────────
  // `autoFocus` on the textarea is ONE `focus()` during commit, and this page is behind
  // `lazy()` in Root.tsx, so that single call lands after a chunk fetch and never repeats.
  // Three separate things then go wrong on the phone this page exists for:
  //
  //   1. ONE ATTEMPT, FIRED LATE. Nothing retries if the engine drops the focus while the
  //      lazily-mounted element is still settling.
  //   2. NO USER ACTIVATION. Both mobile engines raise the on-screen keyboard only for a
  //      focus that happens under user activation, and a home-screen launch carries none.
  //   3. RESUME IS NOT LOAD. An installed standalone app resumed from the app switcher is
  //      not re-navigated — this effect does not re-run — so the caret stays wherever the OS
  //      left it. "Opens the shortcut throughout the day" is mostly resumes, not cold loads.
  //
  // What this fixes is (1) and (3), which are ours, plus as much of (2) as the platforms
  // allow. It does NOT beat WebKit: on iOS a cold launch still will not raise the keyboard,
  // because every documented workaround routes through a tap and the focus-on-open requirement rules
  // out a tap-to-start overlay. What it does buy there is that the textarea is reliably the
  // focused element with the caret in it, and that a resumed app re-focuses — which is the
  // state iOS needs before it will restore a keyboard on its own.
  useEffect(() => {
    let raf = 0;

    // "Is it focused" and "should the keyboard be up" are SEPARATE questions, and collapsing
    // them is a trap: React's `autoFocus` has already focused the textarea by the time this
    // effect first runs, and a resumed app usually still holds DOM focus with the keyboard
    // dismissed — so an early return on "already focused" would skip the keyboard nudge in
    // exactly the two cases it exists for.
    const attempt = () => {
      const el = textareaRef.current;
      if (!el) return;
      const active = document.activeElement;
      if (active !== el) {
        // Never yank the caret out of something the user is already in — after a resume that
        // could be the Send button they were about to press.
        if (active && active !== document.body) return;
        el.focus();
        if (document.activeElement !== el) return; // focus refused; nothing to raise it for
      }
      // Touch-primary only: a device with a physical keyboard has no keyboard to raise, and a
      // Windows touch laptop in a browser tab should keep behaving as it does today.
      if (mediaMatches('(pointer: coarse)')) nudgeVirtualKeyboard();
    };

    // Now and next frame. One live rAF slot, reused by the resume path below.
    const retry = () => {
      attempt();
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(attempt);
    };

    retry();
    // Mount only: the short ladder covers the frames where a lazily-mounted element is still
    // being laid out. A resume needs none of this — the element is long since laid out.
    const timers = [150, 400].map((ms) => setTimeout(attempt, ms));

    const onResume = () => {
      if (document.visibilityState === 'hidden') return;
      if (!isStandaloneLaunch()) return;
      retry();
    };
    window.addEventListener('pageshow', onResume);
    document.addEventListener('visibilitychange', onResume);

    return () => {
      cancelAnimationFrame(raf);
      timers.forEach(clearTimeout);
      window.removeEventListener('pageshow', onResume);
      document.removeEventListener('visibilitychange', onResume);
    };
  }, []);

  const send = async () => {
    const payload = text.trim();
    if (!payload || status.kind === 'sending') return;
    // The last capture's "clear the ✓" timer must not flip this send back to idle.
    if (clearTimer.current) clearTimeout(clearTimer.current);
    setStatus({ kind: 'sending' });
    try {
      const res = await fetch(`${BASE}/api/c/${encodeURIComponent(token)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: payload }),
      });
      if (res.ok) {
        // The box stays editable while sending: clear only what was sent, never a
        // thought typed in the meantime.
        setText((cur) => (cur.trim() === payload ? '' : cur));
        setStatus({ kind: 'captured' });
        // Refocus for rapid-fire capture, clear the ✓ after a beat.
        textareaRef.current?.focus();
        if (clearTimer.current) clearTimeout(clearTimer.current);
        clearTimer.current = setTimeout(() => setStatus({ kind: 'idle' }), 2500);
      } else {
        const body = await res.json().catch(() => null);
        setStatus({ kind: 'error', message: messageFor(res.status, body) });
      }
    } catch {
      setStatus({ kind: 'error', message: 'Network error — try again.' });
    }
  };

  return (
    <div className="min-h-screen bg-sand flex flex-col">
      <header className="bg-cream border-b border-line-faint px-4 py-3 flex items-center gap-3">
        <Logo className="h-7 w-7" />
        <span className="font-heading font-semibold text-charcoal text-sm">{APP_TITLE}</span>
      </header>
      <main className="flex-1 flex items-start justify-center px-3 sm:px-4 py-6 sm:py-8">
        <div className="w-full max-w-xl">
          <h1 className="font-heading text-2xl font-bold text-charcoal">
            Capture
            <span className="ml-2 text-sm font-body font-normal text-muted">straight to your inbox</span>
          </h1>
          <form
            className="mt-4"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder="What's on your mind?"
              rows={4}
              /* 16px font — anything smaller makes iOS zoom the page on focus */
              className="w-full rounded-xl border border-line bg-cream p-4 text-base text-charcoal placeholder:text-muted focus:border-brand focus:outline-none"
              /* The first focus attempt, and the only one desktop ever needs. The retry ladder
                 in the focus-on-open effect above is layered ON TOP of it, not a replacement — every
                 attempt there short-circuits once this one has landed. Don't delete either half. */
              autoFocus
            />
            <div className="mt-3 flex items-center gap-3">
              <button
                type="submit"
                disabled={!text.trim() || status.kind === 'sending'}
                className="rounded-lg bg-brand-dark px-6 py-2.5 font-heading text-white hover:bg-brand-deep disabled:opacity-40"
              >
                {status.kind === 'sending' ? 'Sending…' : 'Send'}
              </button>
              {status.kind === 'captured' && (
                <span className="text-sm font-semibold text-green-700 dark:text-green-400">captured ✓</span>
              )}
              {status.kind === 'error' && <span className="text-sm text-brand-ink">{status.message}</span>}
            </div>
          </form>
          <p className="mt-6 text-xs text-muted">
            Tip: add this page to your phone's home screen. Cmd/Ctrl+Enter sends.
          </p>
        </div>
      </main>
    </div>
  );
}
