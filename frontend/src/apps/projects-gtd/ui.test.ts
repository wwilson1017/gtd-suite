import { describe, expect, it } from 'vitest';
import { markMentions, on, plain, setMentionNames, when } from './ui';

describe('ui text helpers', () => {
  it('flattens markdown for a one-line preview', () => {
    expect(plain('We start **Monday**.\n\n- Demo the [old](https://x.y) cabinets\n- [ ] tile')).toBe(
      'We start Monday. Demo the old cabinets tile',
    );
  });
  it('says when the way Basecamp bylines do', () => {
    const now = new Date(2026, 9, 13, 15, 0);
    expect(on(new Date(2026, 9, 13, 9, 5).toISOString(), now)).toBe('today at 9:05am');
    expect(on(new Date(2026, 4, 25, 9, 5).toISOString(), now)).toBe('on May 25');
    expect(when(new Date(2025, 4, 25).toISOString(), now)).toBe('May 25, 2025');
  });

  it('bolds @mentions of people on the account, longest name first', () => {
    setMentionNames(['Ann', 'Ann Lee', 'Claude']);
    expect(markMentions('@ann lee and (@Claude), not mail@Claude or @Annabel or [x](https://a.b/@Ann)')).toBe(
      '**@ann lee** and (**@Claude**), not mail@Claude or @Annabel or [x](https://a.b/@Ann)',
    );
  });
});
