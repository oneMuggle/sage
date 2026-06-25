import { useCallback, useState } from 'react';

import {
  areSiderOrdersEqual,
  reconcileStoredSiderOrder,
  reorderSiderIds,
  type SiderOrder,
} from '../../shared/lib/dnd/siderOrder';

export const SIDER_SECTIONS_STORAGE_KEY = 'sage:sider:sections:v1';

interface SiderSectionsState {
  order: string[];
  collapsed: string[];
}

function readSectionsState(defaultOrder: readonly string[]): SiderSectionsState {
  const fallback: SiderSectionsState = { order: [...defaultOrder], collapsed: [] };
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(SIDER_SECTIONS_STORAGE_KEY);
  } catch {
    return fallback;
  }
  if (!raw) return fallback;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return fallback;
    const obj = parsed as { order?: unknown; collapsed?: unknown };
    const storedOrder = Array.isArray(obj.order)
      ? obj.order.filter((x): x is string => typeof x === 'string')
      : [];
    const storedCollapsed = Array.isArray(obj.collapsed)
      ? obj.collapsed.filter((x): x is string => typeof x === 'string')
      : [];
    const reconciled = reconcileStoredSiderOrder(storedOrder, [...defaultOrder]);
    return { order: reconciled, collapsed: storedCollapsed };
  } catch {
    return fallback;
  }
}

function writeSectionsState(state: SiderSectionsState): void {
  try {
    localStorage.setItem(SIDER_SECTIONS_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // localStorage unavailable
  }
}

export interface UseSiderSectionsResult {
  order: SiderOrder;
  collapsed: Set<string>;
  toggleCollapsed: (key: string) => void;
  reorderSections: (from: number, to: number) => void;
}

export function useSiderSections(defaultOrder: readonly string[]): UseSiderSectionsResult {
  const [state, setState] = useState<SiderSectionsState>(() => readSectionsState(defaultOrder));

  const toggleCollapsed = useCallback((key: string) => {
    setState((prev) => {
      const isCollapsed = prev.collapsed.includes(key);
      const nextCollapsed = isCollapsed
        ? prev.collapsed.filter((k) => k !== key)
        : [...prev.collapsed, key];
      const next: SiderSectionsState = { ...prev, collapsed: nextCollapsed };
      writeSectionsState(next);
      return next;
    });
  }, []);

  const reorderSections = useCallback((from: number, to: number) => {
    setState((prev) => {
      const nextOrder = reorderSiderIds(prev.order, from, to);
      if (areSiderOrdersEqual(prev.order, nextOrder)) return prev;
      const next: SiderSectionsState = { ...prev, order: nextOrder };
      writeSectionsState(next);
      return next;
    });
  }, []);

  return {
    order: state.order,
    collapsed: new Set(state.collapsed),
    toggleCollapsed,
    reorderSections,
  };
}
