/**
 * 自主目标详情页
 *
 * 展示单个目标的完整信息：
 * - 基本信息 + 执行控制
 * - 进度 + 检查点列表
 * - 执行报告（轮次、任务成功/失败、token 消耗）
 */
import { ArrowLeft, Play, Pause, XCircle, Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useState, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import * as goalApi from '../../entities/autonomous-goals/goalApi';
import { useGoalStore } from '../../entities/autonomous-goals/goalStore';
import type { Checkpoint, Goal, GoalStatus } from '../../entities/autonomous-goals/types';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';
import { PageHeader } from '../../shared/ui';
import { GoalProgress } from '../../widgets/autonomous-goals/GoalProgress';

const STATUS_LABEL: Record<GoalStatus, string> = {
  pending: '等待中',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_VARIANT: Record<GoalStatus, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  pending: 'secondary',
  running: 'default',
  paused: 'outline',
  completed: 'default',
  failed: 'destructive',
  cancelled: 'outline',
};

export function GoalDetailPage() {
  const { goalId } = useParams<{ goalId: string }>();
  const navigate = useNavigate();
  const refreshOne = useGoalStore((s) => s.refreshOne);

  const [goal, setGoal] = useState<Goal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Execution report state (loaded separately)
  const [report, setReport] = useState<{
    total_rounds: number;
    duration_hours: number;
    total_tasks: number;
    tasks_succeeded: number;
    tasks_failed: number;
    total_tokens_used: number;
  } | null>(null);

  const loadData = useCallback(async () => {
    if (!goalId) return;
    setLoading(true);
    setError(null);
    try {
      const [g, r] = await Promise.all([
        goalApi.getGoal(goalId),
        goalApi.getExecutionReport(goalId).catch(() => null),
      ]);
      setGoal(g);
      setReport(r);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [goalId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Auto-refresh for running goals (every 5s)
  useEffect(() => {
    if (goal?.status !== 'running') return;
    const interval = setInterval(() => {
      void refreshOne(goal.id);
      void loadData();
    }, 5000);
    return () => clearInterval(interval);
  }, [goal?.status, goal?.id, refreshOne, loadData]);

  if (loading) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageHeader title="目标详情" />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-text-muted" />
        </div>
      </div>
    );
  }

  if (error || !goal) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <PageHeader title="目标详情" />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-destructive mb-4">{error || '目标不存在'}</p>
            <Button variant="primary" onClick={() => navigate('/goals')}>
              返回列表
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <PageHeader
        title={goal.name}
        actions={
          <Button variant="ghost" size="sm" onClick={() => navigate('/goals')}>
            <ArrowLeft className="w-4 h-4 mr-1" />
            返回
          </Button>
        }
      />

      <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto w-full space-y-4">
        {/* Status + Actions */}
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Badge variant={STATUS_VARIANT[goal.status]}>{STATUS_LABEL[goal.status]}</Badge>
                {goal.degradation_level !== 'none' && (
                  <Badge variant="destructive">{goal.degradation_level}</Badge>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                {goal.status === 'pending' && (
                  <Button size="sm" variant="primary" onClick={() => void handleStart()}>
                    <Play className="w-3.5 h-3.5 mr-1" />
                    启动
                  </Button>
                )}
                {goal.status === 'running' && (
                  <Button size="sm" variant="secondary" onClick={() => void handlePause()}>
                    <Pause className="w-3.5 h-3.5 mr-1" />
                    暂停
                  </Button>
                )}
                {(goal.status === 'running' || goal.status === 'paused') && (
                  <Button size="sm" variant="ghost" onClick={() => void handleCancel()}>
                    <XCircle className="w-3.5 h-3.5 mr-1" />
                    取消
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => void loadData()}>
                  <RefreshCw className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
            <p className="text-sm text-text-muted">{goal.description}</p>
          </CardContent>
        </Card>

        {/* Progress */}
        {goal.status !== 'pending' && (
          <Card>
            <CardHeader>
              <CardTitle>执行进度</CardTitle>
            </CardHeader>
            <CardContent>
              <GoalProgress goal={goal} />
            </CardContent>
          </Card>
        )}

        {/* Error */}
        {goal.last_error && (
          <Card>
            <CardContent className="pt-4">
              <div className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">
                {goal.last_error}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Time window & budget */}
        <Card>
          <CardHeader>
            <CardTitle>配置</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-text-muted">闲时窗口</span>
                <p>
                  {goal.time_window.off_peak_start} – {goal.time_window.off_peak_end}
                </p>
              </div>
              <div>
                <span className="text-text-muted">时区</span>
                <p>{goal.time_window.timezone}</p>
              </div>
              <div>
                <span className="text-text-muted">最大轮次</span>
                <p>{goal.budget.max_rounds}</p>
              </div>
              <div>
                <span className="text-text-muted">最大时长</span>
                <p>{goal.budget.max_hours} 小时</p>
              </div>
              <div>
                <span className="text-text-muted">最大 tokens</span>
                <p>{goal.budget.max_tokens.toLocaleString()}</p>
              </div>
              <div>
                <span className="text-text-muted">失败停止</span>
                <p>{goal.budget.stop_on_failure ? '是' : '否'}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Checkpoints */}
        {goal.checkpoints.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>
                检查点 ({goal.checkpoints.filter((c) => c.verified).length}/
                {goal.checkpoints.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {goal.checkpoints.map((cp) => (
                  <CheckpointItem key={cp.id} checkpoint={cp} />
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {/* Execution report */}
        {report && (
          <Card>
            <CardHeader>
              <CardTitle>执行报告</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-text-muted">总轮次</span>
                  <p>{report.total_rounds}</p>
                </div>
                <div>
                  <span className="text-text-muted">执行时长</span>
                  <p>{report.duration_hours.toFixed(1)} 小时</p>
                </div>
                <div>
                  <span className="text-text-muted">任务总数</span>
                  <p>{report.total_tasks}</p>
                </div>
                <div>
                  <span className="text-text-muted">成功 / 失败</span>
                  <p>
                    <span className="text-green-600">{report.tasks_succeeded}</span>
                    {' / '}
                    <span className="text-destructive">{report.tasks_failed}</span>
                  </p>
                </div>
                <div>
                  <span className="text-text-muted">总 token 消耗</span>
                  <p>{report.total_tokens_used.toLocaleString()}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Timestamps */}
        <div className="text-ui-xs text-text-muted space-y-1">
          <p>创建时间: {formatDate(goal.created_at)}</p>
          {goal.started_at && <p>启动时间: {formatDate(goal.started_at)}</p>}
          {goal.completed_at && <p>完成时间: {formatDate(goal.completed_at)}</p>}
        </div>
      </div>
    </div>
  );

  async function handleStart() {
    if (!goalId) return;
    try {
      const updated = await goalApi.startGoal(goalId);
      setGoal(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handlePause() {
    if (!goalId) return;
    try {
      const updated = await goalApi.pauseGoal(goalId);
      setGoal(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCancel() {
    if (!goalId) return;
    try {
      const updated = await goalApi.cancelGoal(goalId);
      setGoal(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }
}

function CheckpointItem({ checkpoint }: { checkpoint: Checkpoint }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      <span
        className={[
          'mt-0.5 w-4 h-4 rounded-full border flex items-center justify-center shrink-0',
          checkpoint.verified
            ? 'border-green-500 bg-green-500/20 text-green-600'
            : 'border-border text-text-muted',
        ].join(' ')}
      >
        {checkpoint.verified ? '✓' : ''}
      </span>
      <div className="min-w-0">
        <p className="text-text">{checkpoint.description}</p>
        <p className="text-ui-xs text-text-muted mt-0.5">
          {checkpoint.type === 'file' && checkpoint.file_path && `文件: ${checkpoint.file_path}`}
          {checkpoint.type === 'command' &&
            checkpoint.verification_command &&
            `命令: ${checkpoint.verification_command}`}
        </p>
      </div>
    </li>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN');
}
