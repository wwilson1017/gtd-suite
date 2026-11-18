import { useMenuLayout, type MenuLayout } from './menuLayout';

/** Top menu / Sidebar. A native select, like ThemeToggle. */
export function MenuLayoutToggle() {
  const [layout, setLayout] = useMenuLayout();
  return (
    <select
      aria-label="Menu layout"
      title="Menu layout"
      value={layout}
      onChange={(e) => setLayout(e.target.value as MenuLayout)}
      className="rounded-lg border border-line bg-cream px-2 py-1.5 text-sm text-charcoal focus:border-brand focus:outline-none"
    >
      <option value="top">Top menu</option>
      <option value="sidebar">Sidebar</option>
    </select>
  );
}
