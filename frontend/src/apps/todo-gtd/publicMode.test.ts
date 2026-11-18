// Todo GTD — publicMode detection. Pins the base / API-base / todoPath contract.
//
// Node-environment (no jsdom): the module reads only window.location.pathname, so
// a tiny window stub exercises every branch. Each case re-imports with a fresh
// module registry, because the module computes its exports once at import time.
import { afterEach, describe, expect, it, vi } from 'vitest';

async function loadAt(pathname: string) {
  vi.resetModules();
  (globalThis as { window?: unknown }).window = { location: { pathname } };
  return import('./publicMode');
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe('publicMode', () => {
  it('is on at /app and under it, with one fixed base and API prefix for every list', async () => {
    for (const pathname of ['/app', '/app/', '/app/inbox', '/app/projects/7']) {
      const m = await loadAt(pathname);
      expect(m.isTodoPublicMode, pathname).toBe(true);
      expect(m.TODO_PUBLIC_BASE).toBe('/app');
      expect(m.TODO_API_BASE).toBe('/api/app');
    }
    // Paths hang off the router basename root.
    const m = await loadAt('/app');
    expect(m.todoPath()).toBe('/');
    expect(m.todoPath('/inbox')).toBe('/inbox');
    expect(m.todoPath('/projects/7')).toBe('/projects/7');
  });

  it('is off everywhere else, the old web links included', async () => {
    for (const pathname of ['/', '/c/CAPTURETOKEN', '/signin/TOKEN', '/w/OLDTOKEN', '/apples']) {
      const m = await loadAt(pathname);
      expect(m.isTodoPublicMode, pathname).toBe(false);
      expect(m.TODO_PUBLIC_BASE).toBeNull();
    }
  });

  it('is off outside a browser', async () => {
    vi.resetModules();
    const m = await import('./publicMode');
    expect(m.TODO_PUBLIC_BASE).toBeNull();
  });
});
