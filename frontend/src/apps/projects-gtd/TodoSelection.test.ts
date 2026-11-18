import { describe, expect, it } from 'vitest';
import type { Todoset } from './api';
import { openTodos } from './TodoSelection';
import type { Item } from './types';

const item = (id: number, type: string, extra: Partial<Item> = {}) => ({ id, type, title: `#${id}`, ...extra }) as Item;

describe('openTodos', () => {
  it('finds every open to-do: loose, in a list, and in a group', () => {
    const set = {
      loose: [item(1, 'todo')],
      loose_completed: [],
      lists: [
        {
          ...item(2, 'todolist'),
          completed_todos: [],
          children: [item(3, 'todo'), item(4, 'todolist_group', { todos: [item(5, 'todo')] })],
        },
      ],
    } as unknown as Todoset;
    expect(openTodos(set).map((t) => t.id)).toEqual([1, 3, 5]);
  });
});
