// Review Store - 审核队列状态管理
import { create } from 'zustand';

import type { ReviewItem } from '../../shared/types/wiki';

interface ReviewStoreState {
  items: ReviewItem[];
  isLoading: boolean;

  setItems: (items: ReviewItem[]) => void;
  addItem: (item: ReviewItem) => void;
  updateItem: (id: string, patch: Partial<ReviewItem>) => void;
  resolveItem: (id: string) => void;
  removeItem: (id: string) => void;
  clearResolved: () => void;
  setLoading: (loading: boolean) => void;
}

export const useReviewStore = create<ReviewStoreState>((set) => ({
  items: [],
  isLoading: false,

  setItems: (items) => set({ items }),
  addItem: (item) => set((state) => ({ items: [...state.items, item] })),
  updateItem: (id, patch) =>
    set((state) => ({
      items: state.items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    })),
  resolveItem: (id) =>
    set((state) => ({
      items: state.items.map((item) => (item.id === id ? { ...item, resolved: true } : item)),
    })),
  removeItem: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
  clearResolved: () => set((state) => ({ items: state.items.filter((i) => !i.resolved) })),
  setLoading: (loading) => set({ isLoading: loading }),
}));
