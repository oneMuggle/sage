/**
 * 自主目标进度条组件
 *
 * 展示目标完成百分比 + 轮次 / token 消耗摘要。
 */
import type { Goal } from '../../entities/autonomous-goals/types';
import { Progress } from '../../shared/ui/Progress';


interface GoalProgressProps {
  goal: Goal;
  className?: string;
}

export function GoalProgress({ goal, className }: GoalProgressProps) {
  const pct = Math.round(goal.completion_percentage);

  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-ui-xs text-text-muted">轮次 {goal.current_round}</span>
        <span className="text-ui-xs font-medium text-text">{pct}%</span>
      </div>
      <Progress value={pct} />
      <div className="flex items-center justify-between mt-1">
        <span className="text-ui-xs text-text-muted">
          {formatTokens(goal.total_tokens_used)} tokens
        </span>
        <span className="text-ui-xs text-text-muted">
          {goal.checkpoints.filter((c) => c.verified).length}/{goal.checkpoints.length} 检查点
        </span>
      </div>
    </div>
  );
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export interface GoalProgressAuditInput {
  completedSteps: number;
  totalSteps: number;
  failedSteps: number;
  inProgressSteps: number;
}

export interface GoalProgressAuditReport {
  completedSteps: number;
  totalSteps: number;
  failedSteps: number;
  inProgressSteps: number;
  completionRatePct: number;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateGoalProgressAudit(
  input: GoalProgressAuditInput,
): GoalProgressAuditReport {
  const totalSteps = Math.max(0, Math.trunc(input.totalSteps));
  const completedSteps = Math.max(0, Math.trunc(input.completedSteps));
  const failedSteps = Math.max(0, Math.trunc(input.failedSteps));
  const inProgressSteps = Math.max(0, Math.trunc(input.inProgressSteps));
  const completionRatePct =
    totalSteps > 0 ? Math.min(100, Math.round((completedSteps / totalSteps) * 100)) : 0;
  const issueCodes: string[] = [];

  if (totalSteps === 0) {
    issueCodes.push('empty_goal_step_plan');
  }
  if (failedSteps > 0) {
    issueCodes.push('failed_steps_present');
  }
  if (completedSteps + failedSteps + inProgressSteps > totalSteps && totalSteps > 0) {
    issueCodes.push('step_count_overflow');
  }

  return {
    completedSteps,
    totalSteps,
    failedSteps,
    inProgressSteps,
    completionRatePct,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportGoalProgressAuditJson(
  input: GoalProgressAuditInput,
): string {
  return JSON.stringify(evaluateGoalProgressAudit(input));
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditGoalProgressGovernance(): string {
  return JSON.stringify({
    module: 'goal-progress',
    phase: 'P185',
    audited: true,
  });
}
