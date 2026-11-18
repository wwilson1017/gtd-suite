// @vitest-environment jsdom
//
// The install card on every Connect page: the steps for this kind of device start
// open, and Todo GTD's card also covers Capture.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InstallGuide } from './InstallGuide';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function render(userAgent: string) {
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(userAgent);
  const host = document.createElement('div');
  await act(async () => {
    createRoot(host).render(<InstallGuide />);
  });
  const open = [...host.querySelectorAll('details')]
    .filter((d) => d.open)
    .map((d) => d.querySelector('summary')!.textContent);
  const icons = [...host.querySelectorAll('figure img')].map((i) => i.getAttribute('src'));
  return { text: host.textContent!, open, icons };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('the install card', () => {
  it('opens the iPhone steps on an iPhone, and covers Capture on Todo GTD', async () => {
    const { text, open } = await render('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)');
    expect(open).toEqual(['iPhone or iPad (Safari)']);
    expect(text).toContain('Add to Home Screen');
    expect(text).toContain('The best way to do GTD is with two apps');
    expect(text).toContain('Then do the same for Capture');
  });

  it('shows the home-screen icons of Todo GTD and Capture', async () => {
    expect((await render('Mozilla/5.0 (iPhone)')).icons).toEqual(['/icon-192.png', '/icon-capture-192.png']);
  });

  it('knows an older iPhone launched it from the home screen', async () => {
    Object.defineProperty(navigator, 'standalone', { value: true, configurable: true });
    try {
      expect((await render('Mozilla/5.0 (iPhone)')).text).toContain('using the installed app');
    } finally {
      delete (navigator as { standalone?: boolean }).standalone;
    }
  });

  it('opens the Android steps on Android, and the computer steps elsewhere', async () => {
    expect((await render('Mozilla/5.0 (Linux; Android 15; Pixel 9)')).open).toEqual(['Android (Chrome)']);
    expect((await render('Mozilla/5.0 (X11; Linux x86_64)')).open).toEqual(['Computer (Chrome or Edge)']);
  });
});
