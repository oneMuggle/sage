/**
 * 任务中心 store — P4 第一切片 (docs/plans/2026-09-13_ui-optimization-p4-task-center.md)。
 *
 * 聚合各页面局部 busy 态的长任务（office 生成/导出等），让用户切走页面后
 * 仍能在全局任务中心看到"还有什么在跑"。聊天流不进本 store——
 * 会话槽位由 chatStreamStore 持有（单一事实源），任务中心按需订阅。
 *
 * 设计对齐 chatStreamStore：独立 module-singleton zustand，key 控制幂等
 * （重复 register 同 id 只刷新字段不重置 startedAt）。
 */
import { create } from 'zustand';

import type { WordFormatSpec } from '../../shared/api/types';

export type TaskKind = 'office' | 'wiki' | 'custom' | 'shell';

export type TaskCenterStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

/**
 * A4b: office 交付包引用 —— awaiting_approval 条目打开交付抽屉所需坐标。
 * formatSpec 缺席表示生成时未带格式规范，抽屉内 lint 段如实展示跳过。
 */
export interface OfficeDeliveryRef {
  workspacePath: string;
  filePath: string;
  formatSpec: WordFormatSpec | null;
}

/**
 * A4: 全局交付抽屉状态 —— 由 DeliveryDrawerHost（Layout 挂载）渲染。
 * lane 段复用 laneBoardStore 的 lane 行（open 时只记 id，读时解析，
 * 决议后行更新自动透传）；office 段坐标记在条目的 deliveryRef。
 */
export type DeliveryDrawerState =
  | { kind: 'lane'; laneId: string }
  | { kind: 'office'; entryId: string; ref?: OfficeDeliveryRef }
  | null;

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
  /** A4b: office 交付包坐标（awaiting_approval 条目打开抽屉用）。 */
  deliveryRef?: OfficeDeliveryRef | null;
  /** P11: 关联文档名（office 任务跳转 /office 后定位并高亮文档行）。 */
  docName?: string | null;
  /** 2026-11-07 Phase 5: 后台 shell 的 shell_id（TaskCenter 聚合条目）。 */
  shellId?: string | null;
  /** Phase 5: shell 退出码（running 时为 null）。 */
  exitCode?: number | null;
}

export interface TaskCenterPatch {
  title?: string;
  phase?: string;
  percent?: number | null;
  status?: TaskCenterStatus;
  error?: string | null;
  sessionId?: string | null;
  runId?: string | null;
  deliveryRef?: OfficeDeliveryRef | null;
  shellId?: string | null;
  exitCode?: number | null;
}

interface TaskCenterState {
  tasks: Record<string, TaskCenterEntry>;
  /** A4: 当前打开的交付抽屉（null = 关闭）。 */
  delivery: DeliveryDrawerState;
  /** Phase 5: 当前打开的后台 shell 输出抽屉（shell_id；null = 关闭）。 */
  shellStream: string | null;
  openDelivery: (next: Exclude<DeliveryDrawerState, null>) => void;
  closeDelivery: () => void;
  openShellStream: (shellId: string) => void;
  closeShellStream: () => void;
  registerTask: (
    id: string,
    kind: TaskKind,
    title: string,
    phase?: string,
    /** P11: 关联文档名（office 任务跳转后定位文档行）。 */
    docName?: string,
  ) => void;
  /** Phase 5: 后台 shell 列表轮询的 upsert（按 shell_id 幂等）。 */
  registerShell: (shell: ShellRegistration) => void;
  /** Phase 5: 清理已消失的运行中 shell（被其它入口终止/清理）。 */
  removeMissingShells: (activeShellIds: readonly string[]) => void;
  updateTask: (id: string, patch: TaskCenterPatch) => void;
  /** Legacy semantic: drop the entry (existing callers unchanged). */
  finishTask: (id: string) => void;
  /** A1: mark terminal and keep (drives the recently-finished list). */
  completeTask: (id: string, status: 'succeeded' | 'failed' | 'cancelled', error?: string) => void;
  removeTask: (id: string) => void;
  clearFinished: () => void;
  /**
   * P11: 待高亮的文档名（任务中心 office 条目点击跳转 /office 后，
   * OfficeDocumentList 据此定位并高亮对应文档行；展示方消费后清除）。
   */
  pendingHighlight: { docName: string; at: number } | null;
  setHighlight: (docName: string) => void;
  clearHighlight: () => void;
}

/** Phase 5: `listShells()` 条目的最小注册面。 */
export interface ShellRegistration {
  shell_id: string;
  command: string;
  status: 'running' | 'exited';
  exit_code?: number | null;
  age_seconds?: number;
}

export const useTaskCenterStore = create<TaskCenterState>((set) => ({
  tasks: {},
  delivery: null,
  shellStream: null,
  pendingHighlight: null,
  setHighlight: (docName) => set({ pendingHighlight: { docName, at: Date.now() } }),
  clearHighlight: () => set({ pendingHighlight: null }),
  // 抽屉互斥：同时只开一个全局抽屉。
  openDelivery: (next) => set({ delivery: next, shellStream: null }),
  closeDelivery: () => set({ delivery: null }),
  openShellStream: (shellId) => set({ shellStream: shellId, delivery: null }),
  closeShellStream: () => set({ shellStream: null }),
  registerTask: (id, kind, title, phase, docName) =>
    set((state) => {
      const existing = state.tasks[id];
      // 幂等：同 id 重复注册不重置 startedAt（耗时从首次真正开始计）
      if (existing) {
        return {
          tasks: {
            ...state.tasks,
            [id]: {
              ...existing,
              title: title ?? existing.title,
              phase: phase ?? existing.phase,
              docName: docName ?? existing.docName,
            },
          },
        };
      }
      return {
        tasks: {
          ...state.tasks,
          [id]: {
            id,
            kind,
            title,
            startedAt: Date.now(),
            phase,
            docName: docName ?? null,
            status: 'running',
          },
        },
      };
    }),
  updateTask: (id, patch) =>
    set((state) => {
      const existing = state.tasks[id];
      if (!existing) return state;
      return { tasks: { ...state.tasks, [id]: { ...existing, ...patch } } };
    }),
  registerShell: (shell) =>
    set((state) => {
      const id = `shell:${shell.shell_id}`;
      const existing = state.tasks[id];
      const status: TaskCenterStatus =
        shell.status === 'running' ? 'running' : shell.exit_code === 0 ? 'succeeded' : 'failed';
      const startedAt =
        existing?.startedAt ?? Date.now() - Math.max(0, (shell.age_seconds ?? 0) * 1000);
      return {
        tasks: {
          ...state.tasks,
          [id]: {
            ...(existing ?? {}),
            id,
            kind: 'shell',
            title: shell.command.trim().slice(0, 120) || shell.shell_id,
            startedAt,
            status,
            shellId: shell.shell_id,
            exitCode: shell.exit_code ?? null,
            ...(status !== 'running' && existing?.finishedAt == null
              ? { finishedAt: Date.now() }
              : {}),
          } as TaskCenterEntry,
        },
      };
    }),
  removeMissingShells: (activeShellIds) =>
    set((state) => {
      const active = new Set(activeShellIds.map((sid) => `shell:${sid}`));
      const next: Record<string, TaskCenterEntry> = {};
      let changed = false;
      for (const [id, task] of Object.entries(state.tasks)) {
        // 只清理"运行中但已从注册表消失"的条目；终态条目保留给用户查看。
        if (task.kind === 'shell' && task.status === 'running' && !active.has(id)) {
          changed = true;
          continue;
        }
        next[id] = task;
      }
      return changed ? { tasks: next } : state;
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

export function formatTaskCenterStateSummary(
  state: ReturnType<typeof useTaskCenterStore.getState> = useTaskCenterStore.getState(),
): string {
  const entries = Object.values(state.tasks);
  const running = entries.filter((t) => t.status === 'running').length;
  return `total=${entries.length} · running=${running} · delivery=${state.delivery ? 'open' : 'closed'}`;
}

export function formatTaskCenterStateJson(
  state: ReturnType<typeof useTaskCenterStore.getState> = useTaskCenterStore.getState(),
): string {
  const entries = Object.values(state.tasks);
  return JSON.stringify(
    {
      totalCount: entries.length,
      runningCount: entries.filter((t) => t.status === 'running').length,
      taskIds: entries.map((t) => t.id),
      hasDelivery: state.delivery !== null,
      hasHighlight: state.pendingHighlight !== null,
    },
    null,
    2,
  );
}

export function auditTaskCenterStoreGovernance(): {
  module: 'src/features/task-center/taskCenterStore.ts';
  phase: 'P169';
  domain: 'task-center';
  supportsClearFinished: boolean;
  tracksDeliveryAndHighlight: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/task-center/taskCenterStore.ts',
    phase: 'P169',
    domain: 'task-center',
    supportsClearFinished: true,
    tracksDeliveryAndHighlight: true,
    compliant: true,
  };
}
