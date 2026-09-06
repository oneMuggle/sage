// Queue Store - 摄入队列状态管理 (持久化队列,崩溃恢复,取消/重试)
import { create } from 'zustand';

import {
  queueAddTask,
  queueCancelTask,
  queueClearTasks,
  queueGetStatus,
  queueListTasks,
  queueRetryTask,
} from '../../shared/api-client/wiki';
import type { IngestTask, QueueStatus, QueueStatusSummary } from '../../shared/api-client/wiki';

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
