// src/features/task-center/unifiedTaskModel.ts
//
// 统一任务模型：六种异构任务源 → 单一 UnifiedTaskEntry。
// 只在 features 层（shared 不得导入 features，见 eslint.config.js FSD 规则）。
import type { Goal, GoalStatus } from '../../entities/autonomous-goals/types';
import type {
  DirectoryRun,
  DirectoryRunStatus,
  DirectoryTask,
} from '../../shared/api/orchRunClient';
import type { Lane, LaneStatus, ScheduledTask, Todo, TodoItemStatus } from '../../shared/api/types';
import type { TaskStatusValue } from '../../shared/api/types/chatAndEventTypes';

import type { TaskCenterEntry, TaskCenterStatus } from './taskCenterStore';
import { TERMINAL_TASK_STATUSES } from './taskCenterStore';

export type UnifiedTaskSource =
  | 'registry'
  | 'chat'
  | 'lane'
  | 'subagent'
  | 'run'
  | 'goal'
  | 'todo'
  | 'scheduled';

/**
 * 点击语义覆盖：缺省（null）表示"走 detailPath 路由跳转"。
 * A4 交付验收 / 后台 shell 输出抽屉需要优先于路由跳转。
 */
export type UnifiedTaskOpenTarget =
  | { kind: 'shell'; shellId: string }
  | { kind: 'lane-delivery'; laneId: string }
  | { kind: 'office-delivery'; entryId: string }
  | {
      kind: 'subagent-thread';
      sessionId: string;
      runId: string;
      taskId: string;
    }
  // M4.2: run 级行（无可见子任务时的兜底）—— 打开会话并聚焦右栏进度。
  | { kind: 'run-progress'; sessionId: string; runId: string };

export interface UnifiedTaskEntry {
  /** 全局唯一：`<source>:<rawId>` */
  id: string;
  source: UnifiedTaskSource;
  title: string;
  status: TaskCenterStatus;
  /** epoch ms；无则 null */
  startedAt: number | null;
  updatedAt: number | null;
  /** 0-100；无则 null（不伪造） */
  percent: number | null;
  error: string | null;
  cancellable: boolean;
  /** 归属路由（展示 + 兜底跳转）；null = 无归页 */
  detailPath: string | null;
  /** 覆盖 detailPath 的点击语义（交付抽屉 / shell 抽屉）；null = 走 detailPath */
  openTarget: UnifiedTaskOpenTarget | null;
  cancelRef: { source: UnifiedTaskSource; rawId: string } | null;
  meta: Record<string, string | number | null>;
}

export const GOAL_STATUS_MAP: Readonly<Record<GoalStatus, TaskCenterStatus>> = {
  pending: 'queued',
  running: 'running',
  paused: 'paused',
  completed: 'succeeded',
  failed: 'failed',
  cancelled: 'cancelled',
};

export const TODO_STATUS_MAP: Readonly<Record<TodoItemStatus, TaskCenterStatus>> = {
  pending: 'queued',
  in_progress: 'running',
  completed: 'succeeded',
  cancelled: 'cancelled',
};

export const SCHEDULED_STATUS_MAP: Readonly<
  Record<NonNullable<ScheduledTask['last_status']>, TaskCenterStatus>
> = {
  never: 'queued',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
};

export const LANE_STATUS_MAP: Readonly<Record<LaneStatus, TaskCenterStatus>> = {
  created: 'queued',
  ready: 'queued',
  running: 'running',
  blocked: 'awaiting_approval',
  succeeded: 'succeeded',
  failed: 'failed',
  stopped: 'cancelled',
  cancelled: 'cancelled',
};

/** M2.4: 编排任务板子任务状态 → 任务中心状态。 */
export const SUBAGENT_STATUS_MAP: Readonly<Record<TaskStatusValue, TaskCenterStatus>> = {
  queued: 'queued',
  running: 'running',
  paused: 'paused',
  done: 'succeeded',
  failed: 'failed',
  cancelled: 'cancelled',
  skipped: 'cancelled',
};

/** M2.4: 任务中心只展示活跃 + 失败的子代理任务（done 在 run 摘要/transcript 回看）。 */
export function isSubagentTaskVisible(status: TaskStatusValue): boolean {
  return status === 'queued' || status === 'running' || status === 'paused' || status === 'failed';
}

/** M4.2: canonical run 状态（orch_runs.status）→ 任务中心状态。 */
export const CANONICAL_RUN_STATUS_MAP: Readonly<Record<DirectoryRunStatus, TaskCenterStatus>> = {
  running: 'running',
  completed: 'succeeded',
  failed: 'failed',
  cancelled: 'cancelled',
};

/** M4.2: run 级行仅展示活跃 + 失败；completed/cancelled 属于已结束噪音。 */
export function isCanonicalRunVisible(status: DirectoryRunStatus): boolean {
  return status === 'running' || status === 'failed';
}

export const STATUS_PRIORITY: Readonly<Record<TaskCenterStatus, number>> = {
  failed: 0,
  awaiting_approval: 1,
  running: 2,
  paused: 3,
  queued: 4,
  succeeded: 5,
  cancelled: 6,
};

export interface ChatTaskInput {
  sessionId: string;
  title: string;
  /** 首见时间（epoch ms），由 useUnifiedTasks 的 ref 提供 */
  firstSeenAt: number;
}

/** A1: lanes worth surfacing (live work plus failures). */
export function isLaneVisible(status: LaneStatus): boolean {
  return (
    status === 'created' ||
    status === 'ready' ||
    status === 'running' ||
    status === 'blocked' ||
    status === 'failed'
  );
}

/** A4: 待验收 lane —— succeeded 且尚未决议。 */
export function isLaneAwaitingDecision(lane: Lane): boolean {
  if (lane.status !== 'succeeded') return false;
  const meta = lane.metadata ?? {};
  return typeof meta.accepted_at !== 'number' && typeof meta.rejected_at !== 'number';
}

export function isLaneCancellable(status: LaneStatus): boolean {
  return status === 'created' || status === 'ready' || status === 'running' || status === 'blocked';
}

function safeIsoToMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function nonEmpty(value: string | null | undefined, fallback: string): string {
  const trimmed = (value ?? '').trim();
  return trimmed.length > 0 ? trimmed : fallback;
}

export function normalizeRegistryTask(entry: TaskCenterEntry): UnifiedTaskEntry {
  const isShell = entry.kind === 'shell';
  // A4b: office 交付待验收 → 点击直达交付抽屉（历史：旧胶囊的点击分支，现由侧边栏任务中心承接）
  const officeDelivery =
    !isShell && entry.status === 'awaiting_approval' && entry.deliveryRef != null;
  return {
    id: `registry:${entry.id}`,
    source: 'registry',
    title: entry.phase ? `${entry.title} · ${entry.phase}` : entry.title,
    status: entry.status,
    startedAt: Number.isFinite(entry.startedAt) ? entry.startedAt : null,
    updatedAt: entry.finishedAt ?? null,
    percent: typeof entry.percent === 'number' ? entry.percent : null,
    error: entry.error ?? null,
    // shell 运行中可 kill；其他 registry 任务沿用既有不可取消语义
    cancellable: isShell && entry.status === 'running' && Boolean(entry.shellId),
    detailPath: isShell
      ? null
      : entry.kind === 'office'
        ? '/office'
        : entry.kind === 'wiki'
          ? '/knowledge'
          : null,
    openTarget: isShell
      ? entry.shellId
        ? { kind: 'shell', shellId: entry.shellId }
        : null
      : officeDelivery
        ? { kind: 'office-delivery', entryId: entry.id }
        : null,
    cancelRef: isShell && entry.shellId ? { source: 'registry', rawId: entry.shellId } : null,
    meta: {
      kind: entry.kind,
      docName: entry.docName ?? null,
      shellId: entry.shellId ?? null,
      exitCode: entry.exitCode ?? null,
    },
  };
}

export function normalizeChatTask(input: ChatTaskInput): UnifiedTaskEntry {
  return {
    id: `chat:${input.sessionId}`,
    source: 'chat',
    title: input.title,
    status: 'running',
    startedAt: input.firstSeenAt,
    updatedAt: null,
    percent: null,
    error: null,
    cancellable: true,
    detailPath: `/chat?session=${encodeURIComponent(input.sessionId)}`,
    openTarget: null,
    cancelRef: { source: 'chat', rawId: input.sessionId },
    meta: { sessionId: input.sessionId },
  };
}

export interface SubagentTaskInput {
  sessionId: string;
  sessionTitle: string;
  runId: string;
  taskId: string;
  agentId: string;
  goal: string;
  status: TaskStatusValue;
  liveStep: string | null;
  waitingApproval: string | null;
  /** running 状态的本地首见时间（epoch ms）。 */
  startedAt: number | null;
  error: string | null;
}

/** M2.4: 编排任务板子任务 → 任务中心条目（活跃/失败可见）。 */
export function normalizeSubagentTask(input: SubagentTaskInput): UnifiedTaskEntry | null {
  if (!isSubagentTaskVisible(input.status)) return null;
  const mapped = input.waitingApproval ? 'awaiting_approval' : SUBAGENT_STATUS_MAP[input.status];
  const goal = (input.goal || '').trim();
  return {
    id: `subagent:${input.sessionId}:${input.runId}:${input.taskId}`,
    source: 'subagent',
    title: goal ? goal.slice(0, 80) : `${input.taskId} · ${input.agentId}`,
    status: mapped,
    startedAt: input.startedAt,
    updatedAt: null,
    percent: null,
    error: input.error,
    cancellable: false,
    detailPath: `/chat?session=${encodeURIComponent(input.sessionId)}`,
    openTarget: {
      kind: 'subagent-thread',
      sessionId: input.sessionId,
      runId: input.runId,
      taskId: input.taskId,
    },
    cancelRef: null,
    meta: {
      sessionId: input.sessionId,
      sessionTitle: input.sessionTitle,
      runId: input.runId,
      taskId: input.taskId,
      agentId: input.agentId,
      liveStep: input.liveStep,
      waitingApproval: input.waitingApproval,
    },
  };
}

/**
 * M4.2: canonical 子任务（orch_tasks 投影）→ 任务中心条目。
 *
 * 与内存行共用 ``subagent:<session>:<run>:<task>`` id：同名条目在
 * useUnifiedTasks 中按 id 合并，canonical 定状态、内存补实时细节。
 * 会话标题不在目录接口中，先用 sessionId 占位（内存行合并时覆盖）。
 */
export function normalizeCanonicalTask(
  run: DirectoryRun,
  task: DirectoryTask,
  sessionTitle?: string | null,
): UnifiedTaskEntry | null {
  const base = normalizeSubagentTask({
    sessionId: run.session_id,
    // 目录接口不带会话标题：调用方可用全局会话列表补齐，缺省 sessionId 占位。
    sessionTitle: (sessionTitle ?? '').trim() || run.session_id,
    runId: run.run_id,
    taskId: task.task_id,
    agentId: task.agent_id,
    goal: task.goal,
    status: task.status,
    liveStep: null,
    waitingApproval: null,
    startedAt: task.started_at,
    error: task.error,
  });
  if (!base) return null;
  return {
    ...base,
    meta: {
      ...base.meta,
      retryCount: task.retry_count,
      depth: task.depth,
    },
  };
}

export interface CanonicalRunProgress {
  total: number;
  /** done + failed + cancelled + skipped —— 已落定数。 */
  settled: number;
  running: number;
  queued: number;
  paused: number;
  failed: number;
  /** 0-100；无任务时为 null（不伪造）。 */
  percent: number | null;
}

export function canonicalRunProgress(tasks: readonly DirectoryTask[]): CanonicalRunProgress {
  let settled = 0;
  let running = 0;
  let queued = 0;
  let paused = 0;
  let failed = 0;
  for (const task of tasks) {
    switch (task.status) {
      case 'done':
      case 'cancelled':
      case 'skipped':
        settled += 1;
        break;
      case 'failed':
        settled += 1;
        failed += 1;
        break;
      case 'running':
        running += 1;
        break;
      case 'queued':
        queued += 1;
        break;
      case 'paused':
        paused += 1;
        break;
    }
  }
  const total = tasks.length;
  return {
    total,
    settled,
    running,
    queued,
    paused,
    failed,
    percent: total > 0 ? Math.round((settled / total) * 100) : null,
  };
}

/**
 * M4.2: canonical run 级兜底行。
 *
 * 正常情况下 run 由子任务行代表；只有**没有可见子任务**时（已确认未派发、
 * 全部 done 后仍在收尾合成、或子任务全部终态后 run 才失败）才出 run 行，
 * 避免同一 run 在任务中心出现两层重复行。
 */
export function normalizeCanonicalRun(run: DirectoryRun): UnifiedTaskEntry | null {
  if (!isCanonicalRunVisible(run.status)) return null;
  if (run.tasks.some((task) => isSubagentTaskVisible(task.status))) return null;
  const progress = canonicalRunProgress(run.tasks);
  const request = (run.original_request ?? '').trim();
  return {
    id: `run:${run.run_id}`,
    source: 'run',
    title: request ? request.slice(0, 80) : run.run_id,
    status: CANONICAL_RUN_STATUS_MAP[run.status],
    startedAt: run.dispatched_at ?? run.created_at,
    updatedAt: null,
    percent: progress.percent,
    error: null,
    cancellable: run.status === 'running',
    detailPath: `/chat?session=${encodeURIComponent(run.session_id)}`,
    openTarget: {
      kind: 'run-progress',
      sessionId: run.session_id,
      runId: run.run_id,
    },
    cancelRef: { source: 'run', rawId: run.run_id },
    meta: {
      sessionId: run.session_id,
      runId: run.run_id,
      taskCount: progress.total,
      settledCount: progress.settled,
    },
  };
}

/**
 * M4.2: canonical 行与内存行合并（同 id）。
 *
 * canonical（DB）是状态真相；唯一例外是内存侧 pending 审批 —— 它在 DB 里
 * 不可见，存在时必须覆盖为 awaiting_approval。内存侧还提供 liveStep
 * 与真实会话标题。
 */
export function mergeSubagentEntries(
  canonical: UnifiedTaskEntry,
  memory: UnifiedTaskEntry,
): UnifiedTaskEntry {
  return {
    ...canonical,
    status: memory.status === 'awaiting_approval' ? 'awaiting_approval' : canonical.status,
    startedAt: canonical.startedAt ?? memory.startedAt,
    error: canonical.error ?? memory.error,
    meta: { ...canonical.meta, ...memory.meta },
  };
}

export function normalizeLaneTask(lane: Lane): UnifiedTaskEntry | null {
  const awaiting = isLaneAwaitingDecision(lane);
  if (!isLaneVisible(lane.status) && !awaiting) return null;
  const status = awaiting ? 'awaiting_approval' : LANE_STATUS_MAP[lane.status];
  return {
    id: `lane:${lane.lane_id}`,
    source: 'lane',
    title: `${lane.task_id}${lane.agent_id ? ` · ${lane.agent_id}` : ''}`,
    status,
    startedAt: lane.started_at ?? null,
    updatedAt: lane.completed_at ?? null,
    percent: null,
    error: lane.error ?? null,
    cancellable: isLaneCancellable(lane.status),
    detailPath: '/orchestration',
    // A4: 待验收 lane 点击直达交付抽屉，而非 /orchestration 路由
    openTarget: awaiting ? { kind: 'lane-delivery', laneId: lane.lane_id } : null,
    cancelRef: { source: 'lane', rawId: lane.lane_id },
    meta: { laneId: lane.lane_id, agentId: lane.agent_id ?? null },
  };
}

export function normalizeGoalTask(goal: Goal): UnifiedTaskEntry | null {
  const status = GOAL_STATUS_MAP[goal.status];
  if (!status) return null;
  const cancellable =
    goal.status === 'pending' || goal.status === 'running' || goal.status === 'paused';
  return {
    id: `goal:${goal.id}`,
    source: 'goal',
    title: nonEmpty(goal.name, goal.id),
    status,
    startedAt: safeIsoToMs(goal.started_at),
    updatedAt: safeIsoToMs(goal.completed_at),
    percent: typeof goal.completion_percentage === 'number' ? goal.completion_percentage : null,
    error: goal.last_error ?? null,
    cancellable,
    detailPath: `/goals/${encodeURIComponent(goal.id)}`,
    openTarget: null,
    cancelRef: cancellable ? { source: 'goal', rawId: goal.id } : null,
    meta: {
      triggerMode: goal.trigger_mode,
      degradation: goal.degradation_level,
      round: goal.current_round,
    },
  };
}

export function normalizeTodoTask(todo: Todo): UnifiedTaskEntry | null {
  // pending 是"定义"不是"正在发生"；cancelled 不展示（spec §4.4）
  if (todo.status !== 'in_progress' && todo.status !== 'completed') return null;
  const id = String(todo.id);
  return {
    id: `todo:${id}`,
    source: 'todo',
    title: nonEmpty(todo.title, id),
    status: TODO_STATUS_MAP[todo.status],
    startedAt: null,
    updatedAt: safeIsoToMs(todo.updated_at),
    percent: null,
    error: null,
    cancellable: false,
    detailPath: '/todos',
    openTarget: null,
    cancelRef: null,
    meta: { priority: todo.priority, projectTag: todo.project_tag ?? null },
  };
}

export function normalizeScheduledTask(task: ScheduledTask): UnifiedTaskEntry | null {
  const last = task.last_status ?? 'never';
  // never / succeeded 不展示：历史成功不是待办（spec §4.4）
  if (last !== 'running' && last !== 'failed') return null;
  return {
    id: `scheduled:${task.id}`,
    source: 'scheduled',
    title: nonEmpty(task.name, task.id),
    status: SCHEDULED_STATUS_MAP[last],
    startedAt: null,
    updatedAt: task.last_attempt ?? null,
    percent: null,
    error: task.last_error ?? null,
    cancellable: false,
    detailPath: '/scheduled',
    openTarget: null,
    cancelRef: null,
    meta: { enabled: task.enabled ? 1 : 0, mode: task.mode ?? 'deliver' },
  };
}

export function compareUnifiedTasks(a: UnifiedTaskEntry, b: UnifiedTaskEntry): number {
  const pa = STATUS_PRIORITY[a.status] ?? 99;
  const pb = STATUS_PRIORITY[b.status] ?? 99;
  if (pa !== pb) return pa - pb;
  if (a.startedAt === null && b.startedAt !== null) return 1;
  if (a.startedAt !== null && b.startedAt === null) return -1;
  if (a.startedAt !== null && b.startedAt !== null && a.startedAt !== b.startedAt) {
    return a.startedAt - b.startedAt;
  }
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function isTerminalStatus(status: TaskCenterStatus): boolean {
  return TERMINAL_TASK_STATUSES.has(status);
}
