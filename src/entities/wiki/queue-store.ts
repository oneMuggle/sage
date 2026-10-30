// Queue Store - 摄入队列状态管理 (持久化队列,崩溃恢复,取消/重试)
import { create } from 'zustand';

import {
  queueAddTask,
  queueCancelTask,
  queueClearTasks,
  queueGetStatus,
  queueListTasks,
  queueProcess,
  queueRetryTask,
} from '../../shared/api-client/wiki';
import type {
  IngestTask,
  QueueProcessResult,
  QueueStatus,
  QueueStatusSummary,
} from '../../shared/api-client/wiki';

interface QueueStoreState {
  tasks: IngestTask[];
  statusSummary: QueueStatusSummary;
  panelOpen: boolean;
  loading: boolean;
  error: string | null;

  // 操作
  loadTasks: (projectPath: string, status?: QueueStatus) => Promise<void>;
  loadStatus: (projectPath: string) => Promise<void>;
  addTask: (projectPath: string, sourcePath: string, maxRetries?: number) => Promise<string | null>;
  cancelTask: (projectPath: string, taskId: string) => Promise<boolean>;
  retryTask: (projectPath: string, taskId: string) => Promise<boolean>;
  clearCompleted: (projectPath: string) => Promise<number>;
  clearAll: (projectPath: string) => Promise<number>;
  processQueue: (projectPath: string, limit?: number) => Promise<QueueProcessResult | null>;

  // UI 控制
  setPanelOpen: (open: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const INITIAL_SUMMARY: QueueStatusSummary = {
  pending: 0,
  processing: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
};

export const useQueueStore = create<QueueStoreState>((set, get) => ({
  tasks: [],
  statusSummary: INITIAL_SUMMARY,
  panelOpen: false,
  loading: false,
  error: null,

  loadTasks: async (projectPath, status) => {
    set({ loading: true, error: null });
    try {
      const response = await queueListTasks(projectPath, status);
      set({ tasks: response.tasks, loading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载队列失败';
      set({ error: message, loading: false });
    }
  },

  loadStatus: async (projectPath) => {
    try {
      const summary = await queueGetStatus(projectPath);
      set({ statusSummary: summary });
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载队列状态失败';
      set({ error: message });
    }
  },

  addTask: async (projectPath, sourcePath, maxRetries) => {
    set({ loading: true, error: null });
    try {
      const response = await queueAddTask(projectPath, sourcePath, maxRetries);
      await get().loadStatus(projectPath);
      set({ loading: false });
      return response.task_id;
    } catch (err) {
      const message = err instanceof Error ? err.message : '添加任务失败';
      set({ error: message, loading: false });
      return null;
    }
  },

  cancelTask: async (projectPath, taskId) => {
    set({ loading: true, error: null });
    try {
      await queueCancelTask(projectPath, taskId);
      await get().loadStatus(projectPath);
      set({ loading: false });
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : '取消任务失败';
      set({ error: message, loading: false });
      return false;
    }
  },

  retryTask: async (projectPath, taskId) => {
    set({ loading: true, error: null });
    try {
      await queueRetryTask(projectPath, taskId);
      await get().loadStatus(projectPath);
      set({ loading: false });
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : '重试任务失败';
      set({ error: message, loading: false });
      return false;
    }
  },

  clearCompleted: async (projectPath) => {
    set({ loading: true, error: null });
    try {
      const response = await queueClearTasks(projectPath, true);
      await get().loadStatus(projectPath);
      set({ loading: false });
      return response.cleared;
    } catch (err) {
      const message = err instanceof Error ? err.message : '清除已完成任务失败';
      set({ error: message, loading: false });
      return 0;
    }
  },

  clearAll: async (projectPath) => {
    set({ loading: true, error: null });
    try {
      const response = await queueClearTasks(projectPath, false);
      await get().loadStatus(projectPath);
      set({ loading: false });
      return response.cleared;
    } catch (err) {
      const message = err instanceof Error ? err.message : '清除所有任务失败';
      set({ error: message, loading: false });
      return 0;
    }
  },

  processQueue: async (projectPath, limit = 1) => {
    set({ loading: true, error: null });
    try {
      const result = await queueProcess(projectPath, limit);
      await get().loadStatus(projectPath);
      await get().loadTasks(projectPath);
      set({ loading: false });
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : '处理队列失败';
      set({ error: message, loading: false });
      return null;
    }
  },

  setPanelOpen: (open) => set({ panelOpen: open }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      tasks: [],
      statusSummary: INITIAL_SUMMARY,
      loading: false,
      error: null,
    }),
}));

/* v8 ignore start */
export function formatQueueStoreSummary(
  summary?: Partial<QueueStatusSummary>,
  taskCount = 0,
  loading = false,
): string {
  const pending = summary?.pending ?? 0;
  const processing = summary?.processing ?? 0;
  const completed = summary?.completed ?? 0;
  const failed = summary?.failed ?? 0;
  return `tasks=${taskCount} · pending=${pending} · processing=${processing} · completed=${completed} · failed=${failed} · loading=${loading}`;
}

export function formatQueueStoreJson(
  summary?: Partial<QueueStatusSummary>,
  taskCount = 0,
  loading = false,
): string {
  return JSON.stringify({
    taskCount,
    pending: summary?.pending ?? 0,
    processing: summary?.processing ?? 0,
    completed: summary?.completed ?? 0,
    failed: summary?.failed ?? 0,
    cancelled: summary?.cancelled ?? 0,
    loading,
  });
}
/* v8 ignore stop */

export function auditWikiQueueStoreGovernance(
  state: {
    pendingCount?: number;
    failedCount?: number;
  } = {},
): {
  module: 'src/entities/wiki/queue-store.ts';
  phase: 'P156';
  pendingCount: number;
  failedCount: number;
  healthy: boolean;
} {
  const pendingCount =
    typeof state.pendingCount === 'number' && Number.isFinite(state.pendingCount)
      ? Math.max(0, Math.trunc(state.pendingCount))
      : 0;
  const failedCount =
    typeof state.failedCount === 'number' && Number.isFinite(state.failedCount)
      ? Math.max(0, Math.trunc(state.failedCount))
      : 0;
  return {
    module: 'src/entities/wiki/queue-store.ts',
    phase: 'P156',
    pendingCount,
    failedCount,
    healthy: failedCount === 0,
  };
}
