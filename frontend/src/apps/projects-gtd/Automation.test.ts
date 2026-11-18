import { describe as group, expect, it } from 'vitest';
import { describe, scheduleWords } from './Automation';

group('scheduled rules in words', () => {
  it('says when a scheduled rule runs, and what it does to which column', () => {
    expect(scheduleWords({ every: 'week', day: 5, time: '16:30' })).toBe('Every Friday at 16:30');
    expect(scheduleWords({ every: 'month', day: 1, time: '08:00' })).toBe('On day 1 of every month at 08:00');
    expect(scheduleWords({ every: 'weekday', time: '09:00' })).toBe('Every weekday at 09:00');
    const n = { columns: new Map([[3, 'Done']]), labels: new Map(), people: new Map() };
    expect(
      describe(
        {
          kind: 'rule',
          trigger: { on: 'scheduled', column: 3, every: 'day', time: '18:00' },
          actions: [{ do: 'archive' }],
        },
        n,
      ),
    ).toBe('Every day at 18:00, for each card in Done: archive it.');
  });
});
