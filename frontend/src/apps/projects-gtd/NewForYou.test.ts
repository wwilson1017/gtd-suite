import { describe, expect, it } from 'vitest';
import { nextDay } from './NewForYou';

describe('nextDay', () => {
  it('is the calendar day after, across months and years', () => {
    expect(nextDay('2026-10-13')).toBe('2026-10-14');
    expect(nextDay('2026-10-31')).toBe('2026-11-01');
    expect(nextDay('2026-12-31')).toBe('2027-01-01');
  });
});
