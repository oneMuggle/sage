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
