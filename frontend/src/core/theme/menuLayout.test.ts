// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MENU_LAYOUT_KEY, readMenuLayout, saveMenuLayout } from './menuLayout';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('menu layout preference', () => {
  it('defaults to the top menu, and ignores a junk stored value', () => {
    expect(readMenuLayout()).toBe('top');
    localStorage.setItem(MENU_LAYOUT_KEY, 'ribbon');
    expect(readMenuLayout()).toBe('top');
  });

  it('remembers sidebar; top clears the stored value', () => {
    saveMenuLayout('sidebar');
    expect(localStorage.getItem(MENU_LAYOUT_KEY)).toBe('sidebar');
    expect(readMenuLayout()).toBe('sidebar');
    saveMenuLayout('top');
    expect(localStorage.getItem(MENU_LAYOUT_KEY)).toBeNull();
    expect(readMenuLayout()).toBe('top');
  });

  it('survives blocked storage: reads as top, saving does not throw', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readMenuLayout()).toBe('top');
    expect(() => saveMenuLayout('sidebar')).not.toThrow();
  });
});
