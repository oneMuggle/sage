import { describe, it, expect } from 'vitest';

import {
  readStoredSiderOrder,
  writeStoredSiderOrder,
  reconcileStoredSiderOrder,
  sortSiderItemsByStoredOrder,
  areSiderOrdersEqual,
  reorderSiderIds,
} from './siderOrder';

describe('siderOrder (pure)', () => {
  it('module exports 6 functions', () => {
    expect(typeof readStoredSiderOrder).toBe('function');
    expect(typeof writeStoredSiderOrder).toBe('function');
    expect(typeof reconcileStoredSiderOrder).toBe('function');
    expect(typeof sortSiderItemsByStoredOrder).toBe('function');
    expect(typeof areSiderOrdersEqual).toBe('function');
    expect(typeof reorderSiderIds).toBe('function');
  });
});

describe('readStoredSiderOrder', () => {
  it('returns [] when input is null/undefined/empty', () => {
    expect(readStoredSiderOrder(null)).toEqual([]);
    expect(readStoredSiderOrder(undefined)).toEqual([]);
    expect(readStoredSiderOrder('')).toEqual([]);
  });

  it('returns array when valid JSON string', () => {
    expect(readStoredSiderOrder(JSON.stringify(['a', 'b', 'c']))).toEqual(['a', 'b', 'c']);
  });

  it('returns [] when JSON is invalid', () => {
    expect(readStoredSiderOrder('not-json')).toEqual([]);
  });

  it('returns [] when data is not an array', () => {
    expect(readStoredSiderOrder(JSON.stringify({ foo: 'bar' }))).toEqual([]);
  });

  it('filters non-string entries', () => {
    expect(readStoredSiderOrder(JSON.stringify(['a', 1, null, 'b']))).toEqual(['a', 'b']);
  });
});

describe('writeStoredSiderOrder', () => {
  it('serializes array to JSON string', () => {
    expect(writeStoredSiderOrder(['a', 'b'])).toBe(JSON.stringify(['a', 'b']));
  });

  it('serializes empty array', () => {
    expect(writeStoredSiderOrder([])).toBe('[]');
  });
});

describe('reconcileStoredSiderOrder', () => {
  it('returns current when prev is empty', () => {
    expect(reconcileStoredSiderOrder([], ['a', 'b'])).toEqual(['a', 'b']);
  });

  it('returns prev when current is empty', () => {
    expect(reconcileStoredSiderOrder(['a', 'b'], [])).toEqual([]);
  });

  it('keeps relative order of existing ids', () => {
    expect(reconcileStoredSiderOrder(['c', 'b', 'a'], ['a', 'b', 'c'])).toEqual(['c', 'b', 'a']);
  });

  it('appends new ids to end', () => {
    expect(reconcileStoredSiderOrder(['a', 'b'], ['a', 'b', 'c', 'd'])).toEqual([
      'a',
      'b',
      'c',
      'd',
    ]);
  });

  it('removes missing ids', () => {
    expect(reconcileStoredSiderOrder(['a', 'b', 'c'], ['a', 'c'])).toEqual(['a', 'c']);
  });

  it('handles mixed scenario', () => {
    // prev: b, d, a (d will be removed, e is new)
    // current: a, b, c, e
    expect(reconcileStoredSiderOrder(['b', 'd', 'a'], ['a', 'b', 'c', 'e'])).toEqual([
      'b',
      'a',
      'c',
      'e',
    ]);
  });
});

describe('sortSiderItemsByStoredOrder', () => {
  const items = [
    { id: 'a', name: 'A' },
    { id: 'b', name: 'B' },
    { id: 'c', name: 'C' },
  ];

  it('sorts items by order', () => {
    expect(sortSiderItemsByStoredOrder(items, ['c', 'a', 'b'])).toEqual([
      { id: 'c', name: 'C' },
      { id: 'a', name: 'A' },
      { id: 'b', name: 'B' },
    ]);
  });

  it('appends items not in order', () => {
    expect(sortSiderItemsByStoredOrder(items, ['c'])).toEqual([
      { id: 'c', name: 'C' },
      { id: 'a', name: 'A' },
      { id: 'b', name: 'B' },
    ]);
  });

  it('returns original order when order is empty', () => {
    expect(sortSiderItemsByStoredOrder(items, [])).toEqual(items);
  });
});

describe('areSiderOrdersEqual', () => {
  it('returns true for identical arrays', () => {
    expect(areSiderOrdersEqual(['a', 'b'], ['a', 'b'])).toBe(true);
  });

  it('returns false for different lengths', () => {
    expect(areSiderOrdersEqual(['a'], ['a', 'b'])).toBe(false);
  });

  it('returns false for different order', () => {
    expect(areSiderOrdersEqual(['a', 'b'], ['b', 'a'])).toBe(false);
  });

  it('returns true for empty arrays', () => {
    expect(areSiderOrdersEqual([], [])).toBe(true);
  });
});

describe('reorderSiderIds', () => {
  it('moves item forward', () => {
    expect(reorderSiderIds(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a']);
  });

  it('moves item backward', () => {
    expect(reorderSiderIds(['a', 'b', 'c'], 2, 0)).toEqual(['c', 'a', 'b']);
  });

  it('returns same array when fromIndex === toIndex', () => {
    expect(reorderSiderIds(['a', 'b', 'c'], 1, 1)).toEqual(['a', 'b', 'c']);
  });

  it('throws when fromIndex out of bounds', () => {
    expect(() => reorderSiderIds(['a', 'b'], 5, 0)).toThrow('from out of range');
  });

  it('throws when toIndex out of bounds', () => {
    expect(() => reorderSiderIds(['a', 'b'], 0, 5)).toThrow('to out of range');
  });
});
