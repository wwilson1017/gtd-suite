// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { BrainLanding } from './BrainLanding';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('Brain landing address', () => {
  it.each([
    ['https://brain.example', 'brain.example'],
    ['https://suite.example:8443/brain', 'suite.example:8443/brain'],
    ['', null],
  ])('shows the configured host and path for %s', async (url, expected) => {
    const host = document.createElement('div');
    const root = createRoot(host);
    try {
      await act(async () => {
        root.render(
          <BrainLanding
            onStart={() => {}}
            busy={false}
            ready={true}
            error=""
            signedIn={false}
            signIn={null}
            apps={url ? { brain: { title: 'Common Brain', url } } : {}}
            config={null}
          />,
        );
      });
      expect(host.querySelector('footer > .mono')?.textContent ?? null).toBe(expected);
    } finally {
      await act(async () => root.unmount());
    }
  });
});
