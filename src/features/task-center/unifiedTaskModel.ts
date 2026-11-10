// src/features/task-center/unifiedTaskModel.ts
//
// 统一任务模型：六种异构任务源 → 单一 UnifiedTaskEntry。
// 只在 features 层（shared 不得导入 features，见 eslint.config.js FSD 规则）。
import type { Goal, GoalStatus } from '../../entities/autonomous-goals/types';
import type { Lane, LaneStatus, ScheduledTask, Todo, TodoItemStatus } from '../../shared/api/types';

import type { TaskCenterEntry, TaskCenterStatus } from './taskCenterStore';
import { TERMINAL_TASK_STATUSES } from './taskCenterStore';

export type UnifiedTaskSource = 'registry' | 'chat' | 'lane' | 'goal' | 'todo' | 'scheduled';

/**
 * 点击语义覆盖：缺省（null）表示"走 detailPath 路由跳转"。
 * A4 交付验收 / 后台 shell 输出抽屉需要优先于路由跳转。
 */
export type UnifiedTaskOpenTarget =
  | { kind: 'shell'; shellId: string }
  | { kind: 'lane-delivery'; laneId: string }
  | { kind: 'office-delivery'; entryId: string };

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
