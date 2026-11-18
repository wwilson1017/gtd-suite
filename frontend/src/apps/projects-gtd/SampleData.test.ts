import { describe, expect, it } from 'vitest';
import { activeSamples, shouldSeed, type SampleInfo } from './SampleData';

describe('shouldSeed', () => {
  const never: SampleInfo = { state: null, projects: [] };
  it('asks only for an account that never had samples and shows no project', () => {
    expect(shouldSeed(never, 0)).toBe(true);
    expect(shouldSeed(never, 1)).toBe(false);
    expect(shouldSeed(never, null)).toBe(false); // Home still loading
    expect(shouldSeed(null, 0)).toBe(false); // state not known yet
    expect(shouldSeed({ state: 'off', projects: [] }, 0)).toBe(false); // turned off: stays off
    expect(shouldSeed({ state: 'on', projects: [] }, 0)).toBe(false);
  });
});

describe('activeSamples', () => {
  it('counts the sample projects that are out, whatever the switch says', () => {
    const p = (status: string) => ({ id: 1, name: 'x', status });
    expect(activeSamples(null)).toBe(0);
    expect(activeSamples({ state: 'on', projects: [p('active'), p('active')] })).toBe(2);
    expect(activeSamples({ state: 'off', projects: [p('archived'), p('archived')] })).toBe(0);
    // Turned off, then one restored from Archived projects: the bar is back for it.
    expect(activeSamples({ state: 'off', projects: [p('active'), p('archived')] })).toBe(1);
  });
});
