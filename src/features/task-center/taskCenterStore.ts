/**
 * 任务中心 store — P4 第一切片 (docs/plans/2026-09-13_ui-optimization-p4-task-center.md)。
 *
 * 聚合各页面局部 busy 态的长任务（office 生成/导出等），让用户切走页面后
 * 仍能在全局悬浮胶囊看到"还有什么在跑"。聊天流不进本 store——
 * TaskCenterWidget 直接读 chatStreamStore 的会话槽位（单一事实源）。
 *
 * 设计对齐 chatStreamStore：独立 module-singleton zustand，key 控制幂等
 * （重复 register 同 id 只刷新字段不重置 startedAt）。
 */
import { create } from 'zustand';

export type TaskKind = 'office' | 'wiki' | 'custom';

export type TaskCenterStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

/** Terminal states stay visible until the user clears them. */
export const TERMINAL_TASK_STATUSES: ReadonlySet<TaskCenterStatus> = new Set([
  'succeeded',
  'failed',
  'cancelled',
]);

export interface TaskCenterEntry {
  id: string;
  kind: TaskKind;
  title: string;
  startedAt: number;
  phase?: string;
  /** P7: 后端上报的百分比（0-100；无百分比通道的任务为空） */
  percent?: number | null;
  /** A1: status, defaults to running (same implicit P4 semantic). */
  status: TaskCenterStatus;
  /** A1: failure reason, shown when status is failed. */
  error?: string | null;
  /** A1: terminal timestamp, written by completeTask. */
  finishedAt?: number | null;
  /** A1: related session, for jump-back. */
  sessionId?: string | null;
  /** A1: related backend run, for orchestration cancel. */
  runId?: string | null;
}

export interface TaskCenterPatch {
  title?: string;
  phase?: string;
  percent?: number | null;
  status?: TaskCenterStatus;
  error?: string | null;
  sessionId?: string | null;
  runId?: string | null;
}

interface TaskCenterState {
  tasks: Record<string, TaskCenterEntry>;
  registerTask: (id: string, kind: TaskKind, title: string, phase?: string) => void;
  updateTask: (id: string, patch: TaskCenterPatch) => void;
  /** Legacy semantic: drop the entry (existing callers unchanged). */
  finishTask: (id: string) => void;
  /** A1: mark terminal and keep (drives the recently-finished list). */
  completeTask: (id: string, status: 'succeeded' | 'failed' | 'cancelled', error?: string) => void;
  removeTask: (id: string) => void;
  clearFinished: () => void;
}

export const useTaskCenterStore = create<TaskCenterState>((set) => ({
  tasks: {},
  registerTask: (id, kind, title, phase) =>
    set((state) => {
      const existing = state.tasks[id];
      // 幂等：同 id 重复注册不重置 startedAt（耗时从首次真正开始计）
      if (existing) {
        return {
          tasks: {
            ...state.tasks,
            [id]: { ...existing, title: title ?? existing.title, phase: phase ?? existing.phase },
          },
        };
      }
      return {
        tasks: {
          ...state.tasks,
          [id]: { id, kind, title, startedAt: Date.now(), phase, status: 'running' },
        },
      };
    }),
  updateTask: (id, patch) =>
    set((state) => {
      const existing = state.tasks[id];
      if (!existing) return state;
      return { tasks: { ...state.tasks, [id]: { ...existing, ...patch } } };
    }),
  finishTask: (id) =>
    set((state) => {
      if (!state.tasks[id]) return state;
      const next = { ...state.tasks };
      delete next[id];
      return { tasks: next };
    }),
  completeTask: (id, status, error) =>
    set((state) => {
      const existing = state.tasks[id];
      if (!existing) return state;
      return {
        tasks: {
          ...state.tasks,
          [id]: { ...existing, status, error: error ?? null, finishedAt: Date.now() },
        },
      };
    }),
  removeTask: (id) =>
    set((state) => {
      if (!state.tasks[id]) return state;
      const next = { ...state.tasks };
      delete next[id];
      return { tasks: next };
    }),
  clearFinished: () =>
    set((state) => {
      const next: Record<string, TaskCenterEntry> = {};
      for (const [id, task] of Object.entries(state.tasks)) {
        if (!TERMINAL_TASK_STATUSES.has(task.status)) next[id] = task;
      }
      return { tasks: next };
    }),
}));
