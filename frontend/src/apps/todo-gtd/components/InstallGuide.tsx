// "Install on your phone": how to put each app of the suite on a home screen as a
// web app (it opens full screen, like a store app). Settings › Install on your phone, in
// every app; Todo GTD's also covers Capture, which installs beside it.
import { BASE, APP, APP_TITLE } from '../../../core/app';

type Device = 'iphone' | 'android' | 'computer';

const STEPS: Record<Device, { label: string; steps: string[] }> = {
  iphone: {
    label: 'iPhone or iPad (Safari)',
    steps: [
      'Tap the Share button: the square with an arrow pointing up. If you don’t see it, tap ••• first.',
      'Scroll down and tap “Add to Home Screen”.',
      'Tap Add.',
    ],
  },
  android: {
    label: 'Android (Chrome)',
    steps: ['Tap the ⋮ menu at the top right.', 'Tap “Add to Home screen” (or “Install app”).', 'Tap Install.'],
  },
  computer: {
    label: 'Computer (Chrome or Edge)',
    steps: ['Click the install icon at the right end of the address bar.', 'Click Install.'],
  },
};

function thisDevice(): Device {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent;
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'iphone';
  if (/Android/.test(ua)) return 'android';
  return 'computer';
}

function installed(): boolean {
  // iOS before 16.4 says so only through navigator.standalone.
  if ((navigator as Navigator & { standalone?: boolean }).standalone === true) return true;
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(display-mode: standalone)').matches
  );
}

function HomeIcon({ src, label }: { src: string; label: string }) {
  return (
    <figure className="flex w-16 flex-col items-center gap-1">
      <img src={src} alt="" className="h-14 w-14 rounded-2xl shadow-sm" />
      <figcaption className="text-center text-xs text-charcoal">{label}</figcaption>
    </figure>
  );
}

export function InstallGuide() {
  const device = thisDevice();
  const todo = APP === 'todo';
  return (
    <section className="rounded-xl border border-line-faint bg-cream p-4">
      <p className="text-sm text-charcoal">
        {todo ? (
          <>
            The best way to do GTD is with two apps on your phone&rsquo;s home screen: <strong>Todo GTD</strong> for
            your lists, and <strong>Capture</strong> to get things out of your head in a couple of taps.
          </>
        ) : (
          <>{APP_TITLE} works best as an app on your phone&rsquo;s home screen.</>
        )}{' '}
        They are web apps: they open full screen like any other app, and there is nothing to download from an app store.
      </p>
      {/* The icons as they will look on the home screen, so people know what to look for. */}
      <div className="mt-3 flex gap-5">
        <HomeIcon src={APP === 'todo' ? BASE + '/icon-192.png' : `${BASE}/icon-${APP}-192.png`} label={APP_TITLE} />
        {todo && <HomeIcon src={BASE + '/icon-capture-192.png'} label="Capture" />}
      </div>
      {installed() && (
        <p className="mt-2 text-xs font-semibold text-charcoal">
          ✓ You&rsquo;re using the installed app on this device.
        </p>
      )}
      {device === 'computer' ? (
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-charcoal">
          <li>
            Open {APP_TITLE} on your phone: in <strong>Devices &amp; sign-in</strong>, make a code and scan it with your
            phone&rsquo;s camera.
          </li>
          <li>On your phone, add it to your home screen:</li>
        </ol>
      ) : (
        <p className="mt-3 text-sm text-charcoal">On this phone, add it to your home screen:</p>
      )}
      <div className="mt-2 space-y-1">
        {(Object.keys(STEPS) as Device[]).map((key) => (
          <details key={key} open={key === device} className="rounded-lg border border-line-faint bg-sand px-3 py-2">
            <summary className="cursor-pointer text-sm font-semibold text-charcoal">{STEPS[key].label}</summary>
            <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-charcoal">
              {STEPS[key].steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </details>
        ))}
      </div>
      <p className="mt-3 text-sm text-charcoal">
        From then on, open it from its icon on your home screen, not from the browser.
      </p>
      {todo && (
        <p className="mt-2 text-sm text-charcoal">
          <strong>Then do the same for Capture.</strong> Open your <strong>Capture link</strong> (in Settings: copy it
          into your phone&rsquo;s browser, or scan its code from a computer) and add that page to your home screen the
          same way. It installs as its own app, with a plus icon.
        </p>
      )}
    </section>
  );
}
