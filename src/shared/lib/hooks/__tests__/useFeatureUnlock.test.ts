import { act, renderHook } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';

import {
  useFeatureUnlock,
  unlockFeature,
  isFeatureUnlocked,
  FEATURE_UNLOCK_STORAGE_KEY,
  FEATURE_UNLOCK_EVENT,
} from '../useFeatureUnlock';

beforeEach(() => {
  localStorage.clear();
});

describe('useFeatureUnlock — hydrate', () => {
  it('is locked when storage is empty', () => {
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(false);
  });

  it('hydrates unlocked state for a stored key', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['skills', 'office']));
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(true);
  });

  it('is locked for a key absent from the stored set', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['office']));
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(false);
  });

  it('falls back to locked on corrupt JSON', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, '{not json');
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(false);
  });

  it('falls back to locked when stored value is not an array', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify({ skills: true }));
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(false);
  });

  it('ignores non-string entries in the stored array', () => {
    // 只有字符串 'skills' 是合法 key；42 / null 被过滤掉。
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['skills', 42, null]));
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(true);
    // 其他未存储的 feature 仍处于锁定态。
    const other = renderHook(() => useFeatureUnlock('office'));
    expect(other.result.current[0]).toBe(false);
  });

  it('does not throw when localStorage.getItem throws', () => {
    const original = localStorage.getItem.bind(localStorage);
    localStorage.getItem = () => {
      throw new Error('SecurityError');
    };
    try {
      const { result } = renderHook(() => useFeatureUnlock('skills'));
      expect(result.current[0]).toBe(false);
    } finally {
      localStorage.getItem = original;
    }
  });
});

describe('useFeatureUnlock — unlock', () => {
  it('unlocks and persists the key', () => {
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(false);
    act(() => result.current[1]());
    expect(result.current[0]).toBe(true);
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('skills');
  });

  it('is idempotent — unlocking twice keeps a single entry', () => {
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    act(() => result.current[1]());
    act(() => result.current[1]());
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored.filter((k: string) => k === 'skills')).toHaveLength(1);
    expect(result.current[0]).toBe(true);
  });

  it('does not clobber other already-unlocked keys', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['office']));
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    act(() => result.current[1]());
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toEqual(expect.arrayContaining(['office', 'skills']));
  });

  it('does not throw when localStorage.setItem throws', () => {
    const original = localStorage.setItem.bind(localStorage);
    localStorage.setItem = () => {
      throw new Error('QuotaExceeded');
    };
    try {
      const { result } = renderHook(() => useFeatureUnlock('skills'));
      act(() => result.current[1]());
      // 写入失败但内存态仍解锁
      expect(result.current[0]).toBe(true);
    } finally {
      localStorage.setItem = original;
    }
  });
});

describe('useFeatureUnlock — sync across instances', () => {
  it('updates a second instance when the first unlocks (custom event)', () => {
    const sidebar = renderHook(() => useFeatureUnlock('skills'));
    const page = renderHook(() => useFeatureUnlock('skills'));
    expect(sidebar.result.current[0]).toBe(false);
    expect(page.result.current[0]).toBe(false);

    act(() => page.result.current[1]());

    expect(page.result.current[0]).toBe(true);
    expect(sidebar.result.current[0]).toBe(true);
  });

  it('does not unlock unrelated keys when another feature unlocks', () => {
    const skills = renderHook(() => useFeatureUnlock('skills'));
    const office = renderHook(() => useFeatureUnlock('office'));

    act(() => skills.result.current[1]());

    expect(skills.result.current[0]).toBe(true);
    expect(office.result.current[0]).toBe(false);
  });

  it('re-reads on a cross-tab storage event', () => {
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(false);

    // 模拟另一个标签页写入了 localStorage 并触发 storage 事件。
    act(() => {
      localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['skills']));
      window.dispatchEvent(new StorageEvent('storage', { key: FEATURE_UNLOCK_STORAGE_KEY }));
    });

    expect(result.current[0]).toBe(true);
  });

  it('ignores storage events for unrelated keys', () => {
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    act(() => {
      localStorage.setItem('some-other-key', JSON.stringify(['skills']));
      window.dispatchEvent(new StorageEvent('storage', { key: 'some-other-key' }));
    });
    expect(result.current[0]).toBe(false);
  });

  it('re-reads on a storage event with null key (cross-tab clear)', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['skills']));
    const { result } = renderHook(() => useFeatureUnlock('skills'));
    expect(result.current[0]).toBe(true);
    // 另一个标签页 clear() 会派发 key === null 的 storage 事件 → 重新读取后回到锁定态。
    act(() => {
      localStorage.clear();
      window.dispatchEvent(new StorageEvent('storage', { key: null }));
    });
    expect(result.current[0]).toBe(false);
  });
});

describe('useFeatureUnlock — re-sync on key change', () => {
  it('re-hydrates when the featureKey prop changes', () => {
    // 'office' 已解锁、'skills' 未解锁。
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['office']));
    const { result, rerender } = renderHook(({ key }) => useFeatureUnlock(key), {
      initialProps: { key: 'skills' },
    });
    expect(result.current[0]).toBe(false);
    // 切换到已解锁的 'office' → 应重新同步为 true，而非停留在旧 key 的状态。
    rerender({ key: 'office' });
    expect(result.current[0]).toBe(true);
  });
});

describe('imperative helpers', () => {
  it('isFeatureUnlocked reads the store', () => {
    expect(isFeatureUnlocked('skills')).toBe(false);
    unlockFeature('skills');
    expect(isFeatureUnlocked('skills')).toBe(true);
  });

  it('unlockFeature broadcasts the custom event with the key', () => {
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent<string>).detail);
    window.addEventListener(FEATURE_UNLOCK_EVENT, listener);
    try {
      unlockFeature('orchestration');
      unlockFeature('office');
    } finally {
      window.removeEventListener(FEATURE_UNLOCK_EVENT, listener);
    }
    expect(seen).toEqual(['orchestration', 'office']);
  });

  it('unlockFeature does not dispatch when already unlocked', () => {
    unlockFeature('skills');
    let dispatched = false;
    const listener = () => {
      dispatched = true;
    };
    window.addEventListener(FEATURE_UNLOCK_EVENT, listener);
    try {
      unlockFeature('skills');
    } finally {
      window.removeEventListener(FEATURE_UNLOCK_EVENT, listener);
    }
    expect(dispatched).toBe(false);
  });
});
