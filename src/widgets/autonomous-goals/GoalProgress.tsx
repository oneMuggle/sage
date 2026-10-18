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
