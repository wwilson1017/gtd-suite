import { useEffect, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { CopyButton } from './CopyButton';

/** One link the app can always show again: load it, copy it, scan it, or rotate it.
 *  Used for the agent link and the write-only capture link. */
export function LinkCard({
  title,
  blurb,
  accent,
  load,
  regenerate,
  regenerateConfirm,
  copyLabel,
  qrHint,
  onUrl,
  children,
}: {
  title: string;
  blurb: React.ReactNode;
  accent: string;
  load: () => Promise<{ url: string }>;
  regenerate: () => Promise<{ url: string }>;
  regenerateConfirm: string;
  /** What the copy button copies, for screen readers ("Copy the agent link"). */
  copyLabel: string;
  /** Shows the link as a QR code with this line under it. Left out for a link no phone scans. */
  qrHint?: string;
  /** Told the link once it loads and again whenever it is regenerated. */
  onUrl?: (url: string) => void;
  /** Rendered under the link once it has loaded. */
  children?: React.ReactNode;
}) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  // Hold the callbacks in refs so the mount-once effect needs no dep on them (the
  // caller passes fresh function identities each render).
  const loadRef = useRef(load);
  const onUrlRef = useRef(onUrl);
  useEffect(() => {
    loadRef.current = load;
    onUrlRef.current = onUrl;
  });

  const show = (link: { url: string }) => {
    setUrl(link.url);
    onUrlRef.current?.(link.url);
  };

  useEffect(() => {
    loadRef
      .current()
      .then(show)
      .catch(() => setError('Could not load this link.'));
  }, []);

  const doRegenerate = async () => {
    if (!window.confirm(regenerateConfirm)) return;
    setBusy(true);
    setError('');
    try {
      show(await regenerate());
    } catch {
      setError('Regenerate failed — try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`rounded-xl border ${accent} p-4`}>
      <h2 className="font-heading text-sm font-bold text-charcoal">{title}</h2>
      <p className="mt-1 text-xs text-muted">{blurb}</p>

      {error && (
        <p role="alert" className="mt-2 text-sm text-brand-ink">
          {error}
        </p>
      )}

      {url && (
        <>
          <div className="mt-3 flex items-center gap-2">
            <input
              readOnly
              value={url}
              aria-label={title}
              onFocus={(e) => e.currentTarget.select()}
              onClick={(e) => e.currentTarget.select()}
              className="min-w-0 flex-1 rounded-lg border border-line bg-sand px-3 py-2 text-xs text-charcoal"
            />
            <CopyButton text={() => url} label={copyLabel} />
          </div>
          {qrHint && (
            <>
              <div className="mt-3 flex justify-center rounded-xl bg-white p-3">
                <QRCodeSVG value={url} size={144} />
              </div>
              <p className="mt-2 text-center text-xs text-muted">{qrHint}</p>
            </>
          )}
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => void doRegenerate()}
              disabled={busy}
              className="rounded-lg border border-line px-3 py-1.5 text-xs font-heading text-brand-ink hover:bg-sand disabled:opacity-40"
            >
              {busy ? 'Working…' : 'Regenerate'}
            </button>
          </div>
          {children}
        </>
      )}
    </div>
  );
}
