import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { useSiderSections, SIDER_SECTIONS_STORAGE_KEY } from './useSiderSections';

const DEFAULT = ['conversations', 'cron', 'project', 'team'];

beforeEach(() => {
  localStorage.clear();
});

describe('useSiderSections — hydrate', () => {
  it('uses defaultOrder when storage is empty', () => {
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    expect(result.current.order).toEqual(DEFAULT);
    expect(result.current.collapsed.size).toBe(0);
  });

  it('hydrates from a valid stored state', () => {
    localStorage.setItem(
      SIDER_SECTIONS_STORAGE_KEY,
      JSON.stringify({ order: ['cron', 'team', 'conversations', 'project'], collapsed: ['cron'] }),
    );
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    expect(result.current.order).toEqual(['cron', 'team', 'conversations', 'project']);
    expect(result.current.collapsed.has('cron')).toBe(true);
  });

  it('drops sections that are no longer in defaultOrder, appends new ones at the end', () => {
    localStorage.setItem(
      SIDER_SECTIONS_STORAGE_KEY,
      JSON.stringify({ order: ['team', 'gone', 'conversations'], collapsed: ['gone'] }),
    );
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    // 'gone' is dropped from order; 'cron' and 'project' (missing) appended
    expect(result.current.order).toEqual(['team', 'conversations', 'cron', 'project']);
    // 'gone' is removed from collapsed because it's no longer a valid key
    expect(result.current.collapsed.has('gone')).toBe(false);
  });

  it('falls back to defaults on corrupt JSON', () => {
    localStorage.setItem(SIDER_SECTIONS_STORAGE_KEY, '{not json');
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    expect(result.current.order).toEqual(DEFAULT);
    expect(result.current.collapsed.size).toBe(0);
  });

  it('falls back to defaults when stored object is malformed', () => {
    localStorage.setItem(SIDER_SECTIONS_STORAGE_KEY, JSON.stringify({ foo: 'bar' }));
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    expect(result.current.order).toEqual(DEFAULT);
  });

  it('does not throw when localStorage.getItem throws', () => {
    const original = localStorage.getItem.bind(localStorage);
    localStorage.getItem = () => {
      throw new Error('SecurityError');
    };
    try {
      const { result } = renderHook(() => useSiderSections(DEFAULT));
      expect(result.current.order).toEqual(DEFAULT);
    } finally {
      localStorage.getItem = original;
    }
  });
});

describe('useSiderSections — toggleCollapsed', () => {
  it('adds a key to collapsed and persists', () => {
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    act(() => result.current.toggleCollapsed('conversations'));
    expect(result.current.collapsed.has('conversations')).toBe(true);
    const stored = JSON.parse(localStorage.getItem(SIDER_SECTIONS_STORAGE_KEY) as string);
    expect(stored.collapsed).toContain('conversations');
  });

  it('removes a key from collapsed on second toggle', () => {
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    act(() => result.current.toggleCollapsed('cron'));
    act(() => result.current.toggleCollapsed('cron'));
    expect(result.current.collapsed.has('cron')).toBe(false);
  });

  it('does not throw when localStorage.setItem throws', () => {
    const original = localStorage.setItem.bind(localStorage);
    localStorage.setItem = () => {
      throw new Error('QuotaExceeded');
    };
    try {
      const { result } = renderHook(() => useSiderSections(DEFAULT));
      act(() => result.current.toggleCollapsed('conversations'));
      expect(result.current.collapsed.has('conversations')).toBe(true);
    } finally {
      localStorage.setItem = original;
    }
  });
});

describe('useSiderSections — reorderSections', () => {
  it('reorders sections and persists', () => {
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    act(() => result.current.reorderSections(0, 3));
    expect(result.current.order).toEqual(['cron', 'project', 'team', 'conversations']);
    const stored = JSON.parse(localStorage.getItem(SIDER_SECTIONS_STORAGE_KEY) as string);
    expect(stored.order).toEqual(['cron', 'project', 'team', 'conversations']);
  });

  it('no-ops when from === to (returns same array reference)', () => {
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    const before = result.current.order;
    act(() => result.current.reorderSections(1, 1));
    expect(result.current.order).toBe(before);
  });

  it('throws on out-of-range indices', () => {
    const { result } = renderHook(() => useSiderSections(DEFAULT));
    expect(() => result.current.reorderSections(0, 99)).toThrow();
  });
});
