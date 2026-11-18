import { describe, expect, it } from 'vitest';
import { mentionPath } from './MyPages';
import { importSummary, pastedTodos } from './TodosPage';

describe('pastedTodos', () => {
  it('makes a to-do of each pasted line, without bullets or checkboxes', () => {
    expect(pastedTodos('- Measure\n* [ ] Order tile\n\n2. Book the fitter\n  [x] Pay deposit  \n• Clean up')).toEqual([
      'Measure',
      'Order tile',
      'Book the fitter',
      'Pay deposit',
      'Clean up',
    ]);
    expect(pastedTodos('Just one')).toEqual(['Just one']);
  });
});

describe('mentionPath', () => {
  it('leads to the chat, the card, or the item the mention is on', () => {
    const m = {
      id: 9,
      board_id: 3,
      board_name: 'K',
      parent_id: null,
      card_id: null,
      excerpt: '',
      creator: null,
      created_at: '',
    };
    expect(mentionPath({ ...m, type: 'chat_line' })).toBe('/p/3/chat');
    expect(mentionPath({ ...m, type: 'comment', parent_id: 5 })).toBe('/i/5');
    expect(mentionPath({ ...m, type: 'comment', card_id: 7 })).toBe('/p/3/cards?card=7');
    expect(mentionPath({ ...m, type: 'message' })).toBe('/i/9');
  });
});

describe('importSummary', () => {
  it('says what an import added', () => {
    expect(importSummary({ lists: 2, groups: 0, todos: 5, subtasks: 1 })).toBe(
      'Added 2 lists, 5 to-dos and 1 subtask.',
    );
    expect(importSummary({ lists: 0, groups: 0, todos: 1, subtasks: 0 })).toBe('Added 1 to-do.');
    expect(importSummary({ lists: 0, groups: 2, todos: 0, subtasks: 0 })).toBe('Added 2 groups.');
  });
});
