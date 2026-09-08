// Lint Store - 文档质量检查状态管理
import { create } from 'zustand';

import { wikiLintRun } from '../../shared/api-client/wiki';
import type { LintItem } from '../../shared/types/wiki';

interface LintStoreState {
  items: LintItem[];
  isLoading: boolean;
  lastRunAt: number | null;
  error: string | null;

  // 后端驱动的 action
  runLint: (projectPath: string) => Promise<void>;

  // 本地控制 action (向后兼容 mock 数据 / UI 过滤)
  setItems: (items: LintItem[]) => void;
  addItem: (item: LintItem) => void;
  removeItem: (id: string) => void;
  clearItems: () => void;
  setLoading: (loading: boolean) => void;
  setLastRunAt: (timestamp: number) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

/** 把后端 `LintResponse.issues` 条目映射成前端 LintItem 形状。 */
function mapBackendIssue(
  raw: {
    type: string;
    severity: string;
    page: string;
    detail: string;
    broken_target?: string | null;
    suggested_target?: string | null;
    suggested_source?: string | null;
    affected_pages?: string[] | null;
  },
  index: number,
): LintItem {
  return {
    id: `lint-${raw.type}-${raw.page}-${index}`,
    type: raw.type as LintItem['type'],
    severity: raw.severity as LintItem['severity'],
    page: raw.page,
    message: raw.detail,
    suggestion: raw.suggested_source ?? raw.suggested_target ?? undefined,
    detail: raw.detail,
    broken_target: raw.broken_target ?? undefined,
    suggested_target: raw.suggested_target ?? undefined,
    suggested_source: raw.suggested_source ?? undefined,
    affected_pages: raw.affected_pages ?? undefined,
  };
}

export const useLintStore = create<LintStoreState>((set) => ({
  items: [],
  isLoading: false,
  lastRunAt: null,
  error: null,

  runLint: async (projectPath) => {
    set({ isLoading: true, error: null });
    try {
      const response = await wikiLintRun(projectPath);
      const items = response.issues.map(mapBackendIssue);
      set({
        items,
        lastRunAt: Date.now(),
        isLoading: false,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : '运行质量检查失败';
      set({ error: message, isLoading: false });
    }
  },

  setItems: (items) => set({ items }),
  addItem: (item) => set((state) => ({ items: [...state.items, item] })),
  removeItem: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
  clearItems: () => set({ items: [] }),
  setLoading: (loading) => set({ isLoading: loading }),
  setLastRunAt: (timestamp) => set({ lastRunAt: timestamp }),
  setError: (error) => set({ error }),
  reset: () => set({ items: [], isLoading: false, lastRunAt: null, error: null }),
}));
