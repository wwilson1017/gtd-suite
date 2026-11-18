// "Watch how": the animated walk-through of connecting Grok, Claude and ChatGPT
// (public/connect-ai.html), opened in a modal from the Connect page.
import { useEffect, useState } from 'react';

export function ConnectAnimation() {
  const [open, setOpen] = useState(false);
  const closeOnEscape = (e: KeyboardEvent) => {
    if (e.key === 'Escape') setOpen(false);
  };
  useEffect(() => {
    if (!open) return;
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [open]);
  const theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-3 inline-flex items-center gap-2 rounded-lg border border-line bg-cream px-3 py-2 text-sm font-heading text-charcoal hover:bg-sand"
      >
        <span aria-hidden="true">▶</span> Watch how: Grok, Claude and ChatGPT
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2 sm:p-6"
          onClick={() => setOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="How to connect your AI"
            className="relative h-full max-h-[860px] w-full max-w-6xl overflow-hidden rounded-2xl bg-cream"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="absolute right-3 top-3 z-10 rounded-lg border border-line bg-cream px-3 py-1.5 text-sm font-heading text-charcoal hover:bg-sand"
            >
              Close
            </button>
            <iframe
              src={`/connect-ai.html?theme=${theme}`}
              title="How to connect your AI"
              className="h-full w-full border-0"
              // Same origin: once a click puts focus inside the walk-through, Escape lands there.
              onLoad={(e) => e.currentTarget.contentWindow?.addEventListener('keydown', closeOnEscape)}
            />
          </div>
        </div>
      )}
    </>
  );
}
