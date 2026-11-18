import { useThemePref, type ThemePref } from './theme';

/** Light / Dark / System. A native select: small, labelled, keyboard-ready. */
export function ThemeToggle({ className = '' }: { className?: string }) {
  const [pref, setPref] = useThemePref();
  return (
    <select
      aria-label="Theme"
      title="Theme"
      value={pref}
      onChange={(e) => setPref(e.target.value as ThemePref)}
      className={`rounded-lg border border-line bg-cream px-2 py-1.5 text-sm text-charcoal focus:border-brand focus:outline-none ${className}`}
    >
      <option value="system">System</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}
