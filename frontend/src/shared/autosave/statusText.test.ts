// The words the ambient indicator says. Copy is the whole feature here — "All
// changes saved" IS the reassurance the user needs — so it is pinned rather than left to
// drift, and the failure states must name themselves rather than reading as saved.
import { describe, expect, it } from 'vitest';

import { STATUS_TONE, saveStatusText } from './statusText';

describe('saveStatusText', () => {
  it('reassures when there is nothing outstanding', () => {
    expect(saveStatusText('idle')).toBe('All changes saved');
    expect(saveStatusText('saved')).toBe('All changes saved');
  });

  it('names the in-between states', () => {
    expect(saveStatusText('dirty')).toBe('Unsaved changes');
    expect(saveStatusText('saving')).toBe('Saving…');
  });

  it('never lets a failure read as saved', () => {
    // Must not name a culprit: a lost-response retry produces the same 409 against your
    // own save, and this is the announced string.
    expect(saveStatusText('conflict')).toBe('Not saved — this record changed');
    expect(saveStatusText('conflict')).not.toContain('someone else');
    expect(saveStatusText('error', 'API error 500: boom')).toBe('Not saved — API error 500: boom');
    expect(saveStatusText('error')).toBe('Not saved');
  });
});

describe('STATUS_TONE', () => {
  it('gives every failure tint a dark-mode variant', () => {
    // A status tint without `dark:` keeps its light value and turns unreadable — the
    // repo-wide rule, and the one thing about this map worth a test.
    expect(STATUS_TONE.conflict).toContain('dark:');
    expect(STATUS_TONE.error).toContain('dark:');
  });
});
