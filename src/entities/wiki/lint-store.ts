// Lint Store - 文档质量检查状态管理
import { create } from 'zustand';

import type { LintItem } from '../../shared/types/wiki';

interface LintStoreState {
  items: LintItem[];
  isLoading: boolean;
  lastRunAt: number | null;

  setItems: (items: LintItem[]) => void;
  addItem: (item: LintItem) => void;
  removeItem: (id: string) => void;
  clearItems: () => void;
  setLoading: (loading: boolean) => void;
  setLastRunAt: (timestamp: number) => void;
}

export const useLintStore = create<LintStoreState>((set) => ({
  items: [],
  isLoading: false,
  lastRunAt: null,

  setItems: (items) => set({ items }),
  addItem: (item) => set((state) => ({ items: [...state.items, item] })),
  removeItem: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
  clearItems: () => set({ items: [] }),
  setLoading: (loading) => set({ isLoading: loading }),
  setLastRunAt: (timestamp) => set({ lastRunAt: timestamp }),
}));
