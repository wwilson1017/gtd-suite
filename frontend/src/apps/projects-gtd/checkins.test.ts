import { describe, expect, it } from 'vitest';
import { scheduleText } from './CheckinsPage';
import type { Item } from './types';

const q = (over: Partial<Item>) => ({ frequency: 'every_day', time: '09:00', days: [1, 2, 3, 4, 5], ...over }) as Item;

describe('scheduleText', () => {
  it('says a check-in schedule in words', () => {
    expect(scheduleText(q({}))).toBe('Asked every weekday at 9am');
    expect(scheduleText(q({ days: [0, 1, 2, 3, 4, 5, 6], time: '16:30' }))).toBe('Asked every day at 4:30pm');
    expect(scheduleText(q({ days: [3, 1] }))).toBe('Asked every Mo, We at 9am');
    expect(scheduleText(q({ frequency: 'every_other_week', days: [5] }))).toBe('Asked every other week on Fr at 9am');
    expect(scheduleText(q({ paused: true }))).toBe('Paused: not asking anyone');
  });
});
