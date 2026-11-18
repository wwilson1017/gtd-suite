// The frame the apps' landing demos share: a phone (from `lg` up) around a working,
// browser-only miniature of the app, with its toast and the "Be the AI" button.
import { useEffect, useState, type ReactNode } from 'react';

/** A demo's toast: a message that clears itself after three seconds. */
export function useToast() {
  const [toast, setToast] = useState('');
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 3000);
    return () => clearTimeout(timer);
  }, [toast]);
  return [toast, setToast] as const;
}

/** A landing page's demo: a phone (from `lg` up; on a real phone the frame would
 *  only waste width) holding the demo, its toast, and the "Be the AI" button. */
export function DemoPhone({
  toast,
  aiLabel,
  onAi,
  children,
}: {
  toast: string;
  aiLabel: string;
  onAi: () => void;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="relative mx-auto max-w-[400px] lg:rounded-[46px] lg:bg-[#141210] lg:p-3 lg:shadow-2xl lg:ring-2 lg:ring-inset lg:ring-[#3a332d]">
        <div
          aria-hidden="true"
          className="absolute left-1/2 top-5 z-10 hidden h-[26px] w-24 -translate-x-1/2 rounded-full bg-[#141210] lg:block"
        />
        <div className="no-scrollbar relative overflow-y-auto rounded-2xl bg-sand text-left text-[15px] lg:h-[640px] lg:rounded-[36px] lg:pt-9">
          {children}
        </div>
        {/* Over the header, not the bottom: the todo demo's filing buttons sit at the bottom. */}
        <p
          role="status"
          aria-live="polite"
          className={`pointer-events-none absolute left-1/2 top-3 z-20 w-max max-w-[85%] -translate-x-1/2 rounded-lg bg-charcoal px-3.5 py-2 text-[13px] text-cream shadow-lg transition-opacity lg:top-14 ${toast ? 'opacity-100' : 'opacity-0'}`}
        >
          {toast}
        </p>
      </div>
      <button
        type="button"
        onClick={onAi}
        className="mx-auto mt-5 block rounded-full border border-white/35 px-5 py-2 font-heading text-sm font-semibold text-white hover:border-white"
      >
        ✦ Be the AI: {aiLabel}
      </button>
      <p className="mt-2 text-center text-[13px]">This is the real thing, running on this page. Try it.</p>
    </div>
  );
}
