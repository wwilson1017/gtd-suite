// @vitest-environment jsdom
//
// A link from one app to a page of another on the same account (hop.ts
// crossAppHref), decided from the server's config. One address: the page itself.
// Separate hosts: the hop to the app, which settles the account on arrival (the
// arriving half is in components/AppBar.test.tsx). An old address: no link.
import { describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({ getConfig: vi.fn(), createSignInLink: vi.fn() }));

import type { AppConfig } from './api';
import { crossAppHref, readHop } from './hop';

const HERE = window.location.origin;

function config(urls: Record<string, string>, moved = ''): AppConfig {
  const apps = Object.fromEntries(Object.entries(urls).map(([key, url]) => [key, { title: key, url }]));
  return { app: 'todo', apps, moved } as AppConfig;
}

describe('crossAppHref', () => {
  it('on one address links to the page itself, in either direction', () => {
    const one = config({ todo: HERE, projects: `${HERE}/projects` });
    expect(crossAppHref(one, 'projects', '/p/4/overview', 7)).toBe(`${HERE}/projects/app/p/4/overview`);
    expect(crossAppHref(one, 'todo', '/projects/9', 7)).toBe(`${HERE}/app/projects/9`);
  });

  it('where the other app has its own host, is the hop to that app and not to the page', () => {
    const apart = config({ todo: HERE, projects: 'https://projects.example' });
    const href = crossAppHref(apart, 'projects', '/p/4/overview', 7);
    expect(href).toBe('https://projects.example/app#from=todo.7');
    // The mark the other host reads on arrival: signed out there, or in another
    // account, it sends the browser back here for a sign-in link.
    expect(readHop(new URL(href!).hash)).toEqual({ from: 'todo', list: 7 });
  });

  it("offers nothing on an app's old address, even to an app at this origin", () => {
    const old = config({ todo: HERE, projects: `${HERE}/projects` }, `${HERE}/projects`);
    expect(crossAppHref(old, 'todo', '/projects/9', 7)).toBeNull();
    expect(crossAppHref(old, 'projects', '/p/4/overview', 7)).toBeNull();
  });

  it('offers nothing for an app this server has no address for', () => {
    expect(crossAppHref(config({ todo: HERE }), 'projects', '/p/4/overview', 7)).toBeNull();
  });
});
