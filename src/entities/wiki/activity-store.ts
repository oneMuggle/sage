// Activity Store - 操作历史追踪状态管理
import { create } from 'zustand';

import type { ActivityItem } from '../../shared/types/wiki';

interface ActivityStoreState {
  items: ActivityItem[];
  maxItems: number;

  setItems: (items: ActivityItem[]) => void;
  addItem: (item: ActivityItem) => void;
  updateItem: (id: string, patch: Partial<ActivityItem>) => void;
  removeItem: (id: string) => void;
  clearItems: () => void;
}

export const useActivityStore = create<ActivityStoreState>((set) => ({
  items: [],
  maxItems: 100,

  setItems: (items) => set({ items }),
  addItem: (item) =>
    set((state) => {
      const newItems = [item, ...state.items].slice(0, state.maxItems);
      return { items: newItems };
    }),
  updateItem: (id, patch) =>
    set((state) => ({
      items: state.items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    })),
  removeItem: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
  clearItems: () => set({ items: [] }),
}));

/* v8 ignore start */
export function formatActivityStoreSummary(
  items: ActivityItem[] = [],
  maxItems = 100,
): string {
  const running = items.filter((item) => item.status === 'running').length;
  const failed = items.filter((item) => item.status === 'error').length;
  return `activities=${items.length}/${maxItems} · running=${running} · errors=${failed}`;
}

export function formatActivityStoreJson(
  items: ActivityItem[] = [],
  maxItems = 100,
): string {
  return JSON.stringify({
    total: items.length,
    maxItems,
    running: items.filter((item) => item.status === 'running').length,
    errors: items.filter((item) => item.status === 'error').length,
  });
}
/* v8 ignore stop */

export function auditWikiActivityStoreGovernance(
  state: {
    activityCount?: number;
    maxRetained?: number;
  } = {},
): {
  module: 'src/entities/wiki/activity-store.ts';
  phase: 'P156';
  activityCount: number;
  maxRetained: number;
  healthy: boolean;
} {
  const activityCount =
    typeof state.activityCount === 'number' && Number.isFinite(state.activityCount)
      ? Math.max(0, Math.trunc(state.activityCount))
      : 0;
  const maxRetained =
    typeof state.maxRetained === 'number' && Number.isFinite(state.maxRetained)
      ? Math.max(1, Math.trunc(state.maxRetained))
      : 200;
  return {
    module: 'src/entities/wiki/activity-store.ts',
    phase: 'P156',
    activityCount,
    maxRetained,
    healthy: activityCount <= maxRetained,
  };
}
