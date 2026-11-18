import { describe, expect, it } from 'vitest';
import { byFolder } from './HomePage';

describe('byFolder', () => {
  it('puts projects in no folder first, then each folder by name, keeping their order', () => {
    const groups = byFolder([
      { id: 1, folder: 'Clients' },
      { id: 2 },
      { id: 3, folder: 'Admin' },
      { id: 4, folder: 'Clients' },
    ]);
    expect([...groups.keys()]).toEqual(['', 'Admin', 'Clients']);
    expect(groups.get('Clients')!.map((p) => p.id)).toEqual([1, 4]);
    expect(groups.get('')!.map((p) => p.id)).toEqual([2]);
  });

  it('keeps a starred project at the top, whatever folder it is in', () => {
    const groups = byFolder([{ id: 1, folder: 'Clients', pinned: 1 }, { id: 2 }, { id: 3, folder: 'Clients' }]);
    expect(groups.get('')!.map((p) => p.id)).toEqual([1, 2]);
    expect(groups.get('Clients')!.map((p) => p.id)).toEqual([3]);
  });
});
