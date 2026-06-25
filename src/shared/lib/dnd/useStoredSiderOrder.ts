import { useState, useEffect, useCallback, useMemo, useRef } from 'react';

import {
  readStoredSiderOrder,
  writeStoredSiderOrder,
  reconcileStoredSiderOrder,
  sortSiderItemsByStoredOrder,
  reorderSiderIds,
  areSiderOrdersEqual,
} from './siderOrder';

interface UseStoredSiderOrderParams<T> {
  storageKey: string;
  items: T[];
  getId: (item: T) => string;
}

interface UseStoredSiderOrderReturn<T> {
  orderedItems: T[];
  reorder: (fromIndex: number, toIndex: number) => void;
  resetOrder: () => void;
}

/**
 * Hook binding localStorage ↔ React state for the sider order.
 *
 * - 首次渲染: 从 localStorage 读, 与 items 做 reconcile, 作为初始 state
 * - items 的 id 集合变化: 自动 reconcile, 更新 state
 * - reorder: 更新顺序 + 持久化
 * - resetOrder: 恢复到当前 items 顺序
 *
 * 容错: localStorage 抛错 → 降级到 [], 不抛
 */
export function useStoredSiderOrder<T>({
  storageKey,
  items,
  getId,
}: UseStoredSiderOrderParams<T>): UseStoredSiderOrderReturn<T> {
  // Derive stable id list: compare by value, not reference
  const prevIdsRef = useRef<string[]>([]);
  const rawIds = items.map(getId);
  if (!areSiderOrdersEqual(prevIdsRef.current, rawIds)) {
    prevIdsRef.current = rawIds;
  }
  const currentIds = prevIdsRef.current;

  const [order, setOrder] = useState<string[]>(() => {
    const raw = readRawFromLocalStorage(storageKey);
    return reconcileStoredSiderOrder(readStoredSiderOrder(raw), currentIds);
  });

  // items id 集合变化时自动 reconcile (useEffect deps on serialized key)
  const idsKey = currentIds.join('\x00');
  useEffect(() => {
    setOrder((prev) => {
      const next = reconcileStoredSiderOrder(prev, currentIds);
      if (areSiderOrdersEqual(prev, next)) return prev;
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  // 持久化
  useEffect(() => {
    const raw = writeStoredSiderOrder(order);
    writeRawToLocalStorage(storageKey, raw);
  }, [storageKey, order]);

  const orderedItems = useMemo(() => {
    const itemsWithId = items.map((item, i) => ({
      item,
      id: currentIds[i],
    }));
    const sorted = sortSiderItemsByStoredOrder(itemsWithId, order);
    return sorted.map((entry) => entry.item);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, order, idsKey]);

  const reorder = useCallback((fromIndex: number, toIndex: number) => {
    setOrder((prev) => reorderSiderIds(prev, fromIndex, toIndex));
  }, []);

  const resetOrder = useCallback(() => {
    setOrder(prevIdsRef.current);
  }, []);

  return { orderedItems, reorder, resetOrder };
}

// ─── localStorage helpers (error-safe) ───────────────────────

function readRawFromLocalStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeRawToLocalStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // SecurityError or quota exceeded — silently ignore
  }
}
