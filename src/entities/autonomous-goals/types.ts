/**
 * 闲时自主目标执行系统 — TypeScript 类型定义
 *
 * 与后端 API (autonomous_goals_router.py) 的 Pydantic 模型对齐。
 */

// ---------- 枚举类型 ----------

export type GoalStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';

export type DegradationLevel = 'none' | 'model_downgrade' | 'task_simplify' | 'stopped';

export type CheckpointType = 'file' | 'command' | 'code' | 'custom';

// ---------- 值对象 ----------

export interface TimeWindow {
  off_peak_start: string; // "HH:MM"
  off_peak_end: string; // "HH:MM"
  weekends_off_peak: boolean;
  holidays: string[]; // "YYYY-MM-DD"
  min_pricing_tier: string;
  timezone: string;
}

export interface ExecutionBudget {
  max_rounds: number;
  max_hours: number;
  max_tokens: number;
  stop_on_failure: boolean;
}

export interface Checkpoint {
  id: string;
  type: CheckpointType;
  description: string;
  file_path: string | null;
  verification_command: string | null;
  expected_pattern: string | null;
  verified: boolean;
}

// ---------- 核心模型 ----------

export interface Goal {
  id: string;
  name: string;
  description: string;
  status: GoalStatus;
  session_id: string | null;
  time_window: TimeWindow;
  budget: ExecutionBudget;
  checkpoints: Checkpoint[];
  current_round: number;
  created_at: string; // ISO 8601
  started_at: string | null;
  completed_at: string | null;
  total_tokens_used: number;
  completion_percentage: number;
  degradation_level: DegradationLevel;
  last_error: string | null;
}

export interface GoalListResponse {
  items: Goal[];
  total: number;
  limit: number;
  offset: number;
}

export interface ExecutionReport {
  goal_id: string;
  goal_name: string;
  status: string;
  total_rounds: number;
  total_tasks: number;
  tasks_succeeded: number;
  tasks_failed: number;
  total_tokens_used: number;
  completion_percentage: number;
  duration_hours: number;
  degradation_level: string;
  last_error: string | null;
}

export interface GenerateCheckpointsResponse {
  goal_id: string;
  generated_count: number;
  checkpoints: Checkpoint[];
}

// ---------- 请求体 ----------

export interface CreateGoalInput {
  name: string;
  description: string;
  session_id?: string;
  time_window?: Partial<TimeWindow>;
  budget?: Partial<ExecutionBudget>;
  auto_generate_checkpoints?: boolean;
}

export interface UpdateGoalInput {
  name?: string;
  description?: string;
  time_window?: Partial<TimeWindow>;
  budget?: Partial<ExecutionBudget>;
  status?: GoalStatus;
}

export function formatGoalAuditSummary(
  goal: Pick<
    Goal,
    'id' | 'name' | 'status' | 'completion_percentage' | 'degradation_level' | 'checkpoints'
  >,
): string {
  const verifiedCount = goal.checkpoints.filter((c) => c.verified).length;
  return `${goal.id} · status=${goal.status} · progress=${goal.completion_percentage}% · checkpoints=${verifiedCount}/${goal.checkpoints.length} · deg=${goal.degradation_level}`;
}

export function formatGoalAuditJson(
  goal: Pick<
    Goal,
    'id' | 'name' | 'status' | 'completion_percentage' | 'degradation_level' | 'checkpoints'
  >,
): string {
  return JSON.stringify(
    {
      id: goal.id,
      name: goal.name,
      status: goal.status,
      completionPercentage: goal.completion_percentage,
      verifiedCheckpoints: goal.checkpoints.filter((c) => c.verified).length,
      totalCheckpoints: goal.checkpoints.length,
      degradationLevel: goal.degradation_level,
    },
    null,
    2,
  );
}

export function auditAutonomousGoalsTypesGovernance(
  state: {
    status?: GoalStatus | string;
    degradationLevel?: DegradationLevel | string;
  } = {},
): {
  module: 'src/entities/autonomous-goals/types.ts';
  phase: 'P153';
  status: GoalStatus;
  degradationLevel: DegradationLevel;
  healthy: boolean;
} {
  const status: GoalStatus =
    state.status === 'pending' ||
    state.status === 'running' ||
    state.status === 'paused' ||
    state.status === 'failed' ||
    state.status === 'cancelled'
      ? state.status
      : 'completed';
  const degradationLevel: DegradationLevel =
    state.degradationLevel === 'model_downgrade' ||
    state.degradationLevel === 'task_simplify' ||
    state.degradationLevel === 'stopped'
      ? state.degradationLevel
      : 'none';
  return {
    module: 'src/entities/autonomous-goals/types.ts',
    phase: 'P153',
    status,
    degradationLevel,
    healthy: status !== 'failed' && degradationLevel !== 'stopped',
  };
}
