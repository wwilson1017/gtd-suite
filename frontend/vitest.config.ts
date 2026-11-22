import { defineConfig } from 'vitest/config';
import { billingAlias } from './vite.config';

/**
 * Frontend unit-test runner.
 *
 * Deliberately a STANDALONE config rather than a `test` block inside `vite.config.ts`:
 * tests skip the react + tailwind plugin pipeline they don't need, and the production
 * build never evaluates any vitest code. It does NOT inherit `vite.config.ts`'s resolve
 * aliases or `define` values: it takes the one alias, `@billing`, from there.
 *
 * Every option below MUST stay nested under `test` — vitest silently ignores these keys
 * at the top level.
 */
export default defineConfig({
  resolve: { alias: billingAlias },
  test: {
    // Plain Node by default; a suite that needs a DOM opts in with
    // `// @vitest-environment jsdom` at the top of the file.
    environment: 'node',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    passWithNoTests: false,
    allowOnly: false,
    expect: { requireAssertions: true },
    // Pin the runner's zone so date-shaped assertions do not depend on the machine.
    env: { TZ: 'America/Chicago' },
  },
});
