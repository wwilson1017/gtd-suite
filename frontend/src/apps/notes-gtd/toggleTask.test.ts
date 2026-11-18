// Ticking a checklist item flips its box in the markdown source, and nothing else.
import { describe, expect, it } from 'vitest';
import { toggleTask } from './toggleTask';

describe('toggleTask', () => {
  it('ticks and unticks the item at the offset', () => {
    expect(toggleTask('- [ ] milk', 0)).toBe('- [x] milk');
    expect(toggleTask('- [x] milk', 0)).toBe('- [ ] milk');
    expect(toggleTask('* [X] milk', 0)).toBe('* [ ] milk');
    expect(toggleTask('1. [ ] first', 0)).toBe('1. [x] first');
  });

  it('flips only the nested, indented item it is pointed at', () => {
    const body = '# Shop\n\n- [ ] milk\n  - [ ] oat\n- [x] eggs';
    const oat = body.indexOf('- [ ] oat');
    expect(toggleTask(body, oat)).toBe('# Shop\n\n- [ ] milk\n  - [x] oat\n- [x] eggs');
    expect(toggleTask(body, body.indexOf('- [x] eggs'))).toBe('# Shop\n\n- [ ] milk\n  - [ ] oat\n- [ ] eggs');
  });

  it('leaves the body alone when the offset is not a task item', () => {
    expect(toggleTask('- plain item', 0)).toBe('- plain item');
    expect(toggleTask('text [ ] here', 0)).toBe('text [ ] here');
    expect(toggleTask('- [ ] milk', 99)).toBe('- [ ] milk');
  });
});
