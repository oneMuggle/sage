import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useStoredSiderOrder } from './useStoredSiderOrder';

const STORAGE_KEY = 'sage:sider:order:v1';

const makeSession = (id: string) => ({ id, title: id });

beforeEach(() => {
  localStorage.clear();
});

describe('useStoredSiderOrder', () => {
  it('module exports a hook function', () => {
    expect(typeof useStoredSiderOrder).toBe('function');
  });

  it('returns orderedItems, reorder, and resetOrder', () => {
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items: [], getId: (x: { id: string }) => x.id }),
    );
    expect(Array.isArray(result.current.orderedItems)).toBe(true);
    expect(typeof result.current.reorder).toBe('function');
    expect(typeof result.current.resetOrder).toBe('function');
  });

  it('returns items unchanged when storage is empty', () => {
    const items = [makeSession('a'), makeSession('b')];
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
    );
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['a', 'b']);
  });

  it('hydrates from stored order and reconciles with current items', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['c', 'a', 'b']));
    const items = [makeSession('a'), makeSession('b'), makeSession('c')];
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
    );
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['c', 'a', 'b']);
  });

  it('reorder updates order and persists to localStorage', () => {
    const items = [makeSession('a'), makeSession('b'), makeSession('c')];
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
    );

    act(() => {
      result.current.reorder(0, 2);
    });

    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['b', 'c', 'a']);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) as string)).toEqual(['b', 'c', 'a']);
  });

  it('resetOrder restores to current items order', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['c', 'b', 'a']));
    const items = [makeSession('a'), makeSession('b'), makeSession('c')];
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
    );
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['c', 'b', 'a']);

    act(() => {
      result.current.resetOrder();
    });

    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['a', 'b', 'c']);
  });

  it('reconciles when items change — appends new ids', () => {
    const items1 = [makeSession('a'), makeSession('b')];
    const { result, rerender } = renderHook(
      ({ items }) => useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
      { initialProps: { items: items1 } },
    );
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['a', 'b']);

    const items2 = [makeSession('a'), makeSession('b'), makeSession('c')];
    rerender({ items: items2 });
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['a', 'b', 'c']);
  });

  it('reconciles when items change — drops removed ids', () => {
    const items1 = [makeSession('a'), makeSession('b'), makeSession('c')];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['c', 'a', 'b']));
    const { result, rerender } = renderHook(
      ({ items }) => useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
      { initialProps: { items: items1 } },
    );
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['c', 'a', 'b']);

    const items2 = [makeSession('a'), makeSession('c')];
    rerender({ items: items2 });
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['c', 'a']);
  });

  it('does not throw when localStorage.getItem throws', () => {
    const original = localStorage.getItem.bind(localStorage);
    localStorage.getItem = () => {
      throw new Error('SecurityError');
    };
    try {
      const items = [makeSession('a')];
      const { result } = renderHook(() =>
        useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
      );
      expect(result.current.orderedItems.map((x) => x.id)).toEqual(['a']);
    } finally {
      localStorage.getItem = original;
    }
  });

  it('does not throw when localStorage.setItem throws', () => {
    const items = [makeSession('a'), makeSession('b')];
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
    );

    const original = localStorage.setItem.bind(localStorage);
    localStorage.setItem = () => {
      throw new Error('QuotaExceeded');
    };
    try {
      act(() => {
        result.current.reorder(0, 1);
      });
      expect(result.current.orderedItems.map((x) => x.id)).toEqual(['b', 'a']);
    } finally {
      localStorage.setItem = original;
    }
  });

  it('treats corrupt JSON in localStorage as empty order', () => {
    localStorage.setItem(STORAGE_KEY, '{not json');
    const items = [makeSession('a')];
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
    );
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['a']);
  });

  it('preserves sort stability for items not in stored order', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['c']));
    const items = [
      makeSession('a'),
      makeSession('b'),
      makeSession('c'),
      makeSession('d'),
    ];
    const { result } = renderHook(() =>
      useStoredSiderOrder({ storageKey: STORAGE_KEY, items, getId: (x) => x.id }),
    );
    // 'c' first (from stored), then a, b, d in original order
    expect(result.current.orderedItems.map((x) => x.id)).toEqual(['c', 'a', 'b', 'd']);
  });
});
