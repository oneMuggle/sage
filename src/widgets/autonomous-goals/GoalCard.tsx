/**
 * 自主目标卡片组件
 *
 * 在列表页中展示单个目标的摘要信息：
 * - 名称 + 状态 Badge
 * - 描述（截断）
 * - 进度条（GoalProgress）
 * - 操作按钮（start/pause/cancel/delete）
 */
import { useNavigate } from 'react-router-dom';
import { Play, Pause, XCircle, Trash2, ChevronRight } from 'lucide-react';

import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import { Card, CardContent } from '../../shared/ui/Card';
import { useGoalStore } from '../../entities/autonomous-goals/goalStore';
import type { Goal, GoalStatus } from '../../entities/autonomous-goals/types';

import { GoalProgress } from './GoalProgress';

interface GoalCardProps {
  goal: Goal;
}

const STATUS_VARIANT: Record<GoalStatus, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  pending: 'secondary',
  running: 'default',
  paused: 'outline',
  completed: 'default',
  failed: 'destructive',
  cancelled: 'outline',
};

const STATUS_LABEL: Record<GoalStatus, string> = {
  pending: '等待中',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

export function GoalCard({ goal }: GoalCardProps) {
  const navigate = useNavigate();
  const start = useGoalStore((s) => s.start);
  const pause = useGoalStore((s) => s.pause);
  const cancel = useGoalStore((s) => s.cancel);
  const remove = useGoalStore((s) => s.delete);

  const handleNavigate = () => navigate(`/goals/${goal.id}`);

  return (
    <Card
      className="hover:border-primary/50 transition-colors cursor-pointer"
      onClick={handleNavigate}
    >
      <CardContent className="pt-4">
        {/* Header: Name + Status + Nav */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold truncate">{goal.name}</h3>
              <Badge variant={STATUS_VARIANT[goal.status]}>{STATUS_LABEL[goal.status]}</Badge>
            </div>
            <p className="text-ui-xs text-text-muted mt-1 line-clamp-2">{goal.description}</p>
          </div>
          <ChevronRight className="w-4 h-4 text-text-muted shrink-0" />
        </div>

        {/* Progress */}
        {goal.status !== 'pending' && <GoalProgress goal={goal} className="mb-3" />}

        {/* Time window summary */}
        <div className="flex items-center gap-3 text-ui-xs text-text-muted mb-3">
          <span>
            闲时: {goal.time_window.off_peak_start}–{goal.time_window.off_peak_end}
          </span>
          <span>
            上限: {goal.budget.max_rounds} 轮 / {goal.budget.max_hours}h
          </span>
        </div>

        {/* Error message */}
        {goal.last_error && (
          <div className="text-ui-xs text-destructive bg-destructive/10 rounded-md px-2 py-1 mb-3 truncate">
            {goal.last_error}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          {goal.status === 'pending' && (
            <Button size="sm" variant="primary" onClick={() => void start(goal.id)}>
              <Play className="w-3.5 h-3.5 mr-1" />
              启动
            </Button>
          )}
          {goal.status === 'running' && (
            <Button size="sm" variant="secondary" onClick={() => void pause(goal.id)}>
              <Pause className="w-3.5 h-3.5 mr-1" />
              暂停
            </Button>
          )}
          {(goal.status === 'running' || goal.status === 'paused') && (
            <Button size="sm" variant="ghost" onClick={() => void cancel(goal.id)}>
              <XCircle className="w-3.5 h-3.5 mr-1" />
              取消
            </Button>
          )}
          {goal.status !== 'running' && (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto text-text-muted hover:text-destructive"
              onClick={() => void remove(goal.id)}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
