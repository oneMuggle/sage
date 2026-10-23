// Review Store - 审核队列状态管理
import { create } from 'zustand';

import { wikiReviewRun } from '../../shared/api-client/wiki';
import type { ReviewItem, ReviewItemRaw } from '../../shared/types/wiki';

interface ReviewStoreState {
  items: ReviewItem[];
  isLoading: boolean;
  lastRunAt: number | null;
  error: string | null;

  // 后端驱动的 action
  runReview: (projectPath: string) => Promise<void>;

  // 本地控制 action (向后兼容 mock 数据 / UI 过滤)
  setItems: (items: ReviewItem[]) => void;
  addItem: (item: ReviewItem) => void;
  updateItem: (id: string, patch: Partial<ReviewItem>) => void;
  resolveItem: (id: string) => void;
  dismissItem: (id: string) => void;
  removeItem: (id: string) => void;
  clearResolved: () => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

/** 把后端 `ReviewResponse.items` 条目映射成前端 ReviewItem 形状。 */
function mapBackendItem(raw: ReviewItemRaw): ReviewItem {
  return {
    id: raw.id,
    type: raw.type,
    title: raw.title,
    description: raw.description,
    affectedPages: raw.affected_pages ?? [],
    resolved: false,
    actions: [],
    confidence: raw.confidence,
    detail: raw.detail,
    suggestion: raw.suggestion,
  };
}

export const useReviewStore = create<ReviewStoreState>((set) => ({
  items: [],
  isLoading: false,
  lastRunAt: null,
  error: null,

  runReview: async (projectPath) => {
    set({ isLoading: true, error: null });
    try {
      const response = await wikiReviewRun(projectPath);
      const items = response.items.map(mapBackendItem);
      set({
        items,
        lastRunAt: Date.now(),
        isLoading: false,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : '运行审核失败';
      set({ error: message, isLoading: false });
    }
  },

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
  dismissItem: (id) =>
    set((state) => ({
      items: state.items.filter((item) => item.id !== id),
    })),
  removeItem: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
  clearResolved: () => set((state) => ({ items: state.items.filter((i) => !i.resolved) })),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  reset: () => set({ items: [], isLoading: false, lastRunAt: null, error: null }),
}));

/* v8 ignore start */
export function formatReviewStoreSummary(
  items: ReviewItem[] = [],
  isLoading = false,
  error: string | null = null,
): string {
  const unresolved = items.filter((item) => !item.resolved).length;
  const status = error ? 'error' : isLoading ? 'loading' : 'idle';
  return `status=${status} · reviews=${items.length} · unresolved=${unresolved}`;
}

export function formatReviewStoreJson(
  items: ReviewItem[] = [],
  isLoading = false,
  error: string | null = null,
): string {
  return JSON.stringify({
    reviewCount: items.length,
    unresolvedCount: items.filter((item) => !item.resolved).length,
    isLoading,
    error,
  });
}
/* v8 ignore stop */

export function auditWikiReviewStoreGovernance(
  state: {
    pendingReviewCount?: number;
    rejectedCount?: number;
  } = {},
): {
  module: 'src/entities/wiki/review-store.ts';
  phase: 'P157';
  pendingReviewCount: number;
  rejectedCount: number;
  healthy: boolean;
} {
  const pendingReviewCount =
    typeof state.pendingReviewCount === 'number' &&
    Number.isFinite(state.pendingReviewCount)
      ? Math.max(0, Math.trunc(state.pendingReviewCount))
      : 0;
  const rejectedCount =
    typeof state.rejectedCount === 'number' && Number.isFinite(state.rejectedCount)
      ? Math.max(0, Math.trunc(state.rejectedCount))
      : 0;
  return {
    module: 'src/entities/wiki/review-store.ts',
    phase: 'P157',
    pendingReviewCount,
    rejectedCount,
    healthy: pendingReviewCount <= 500,
  };
}
