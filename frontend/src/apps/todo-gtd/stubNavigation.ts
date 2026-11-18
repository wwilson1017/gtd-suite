// Test helper: jsdom cannot navigate, so location.reload and location.replace are
// replaced with spies and every other property stays the real location's. Undo
// with vi.unstubAllGlobals(). (An empty proxy target: Location's own methods are
// non-configurable, and a proxy over it may not answer them with anything else.)
import { vi } from 'vitest';

export function stubNavigation() {
  const nav = { reload: vi.fn(), replace: vi.fn() };
  const real = window.location;
  vi.stubGlobal(
    'location',
    new Proxy(
      {},
      {
        get(_, key) {
          if (key === 'reload' || key === 'replace') return nav[key];
          const value = Reflect.get(real, key);
          return typeof value === 'function' ? value.bind(real) : value;
        },
      },
    ),
  );
  return nav;
}
