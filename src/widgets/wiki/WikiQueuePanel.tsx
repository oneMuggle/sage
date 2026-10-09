// WikiQueuePanel - 摄入队列管理界面
import { useEffect, useMemo, useState } from 'react';

import { useQueueStore } from '../../entities/wiki/queue-store';
import type { IngestTask, QueueStatus } from '../../shared/api-client/wiki';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

interface WikiQueuePanelProps {
  projectPath: string;
}

const STATUS_FILTERS: { value: QueueStatus | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '等待' },
  { value: 'processing', label: '处理中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
];

const STATUS_LABEL: Record<QueueStatus, string> = {
  pending: '等待中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_COLOR: Record<QueueStatus, string> = {
  pending: 'bg-bg-subtle text-text-secondary',
  processing: 'bg-info/15 text-info',
  completed: 'bg-success/15 text-success',
  failed: 'bg-error/15 text-error',
  cancelled: 'bg-bg-muted text-muted',
};

function formatRelativeTime(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s 前`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m 前`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h 前`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d 前`;
}

export function WikiQueuePanel({ projectPath }: WikiQueuePanelProps) {
  const tasks = useQueueStore((s) => s.tasks);
  const statusSummary = useQueueStore((s) => s.statusSummary);
  const loading = useQueueStore((s) => s.loading);
  const error = useQueueStore((s) => s.error);
  const loadTasks = useQueueStore((s) => s.loadTasks);
  const loadStatus = useQueueStore((s) => s.loadStatus);
  const cancelTask = useQueueStore((s) => s.cancelTask);
  const retryTask = useQueueStore((s) => s.retryTask);
  const clearCompleted = useQueueStore((s) => s.clearCompleted);
  const clearAll = useQueueStore((s) => s.clearAll);

  const [filter, setFilter] = useState<QueueStatus | 'all'>('all');

  useEffect(() => {
    if (!projectPath) return;
    loadStatus(projectPath);
    loadTasks(projectPath, filter === 'all' ? undefined : filter);
  }, [projectPath, filter, loadStatus, loadTasks]);

  const visibleTasks = useMemo(() => {
    if (filter === 'all') return tasks;
    return tasks.filter((t) => t.status === filter);
  }, [tasks, filter]);

  const totalCount =
    statusSummary.pending +
    statusSummary.processing +
    statusSummary.completed +
    statusSummary.failed +
    statusSummary.cancelled;

  return (
    <div className="flex h-full flex-col">
      {/* 状态摘要 */}
      <div className="border-b border-border bg-bg-muted p-3">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">摄入队列</h3>
          <span className="text-xs text-muted">共 {totalCount} 个任务</span>
        </div>

        <div className="flex flex-wrap gap-2">
          {Object.entries(statusSummary).map(([status, count]) => (
            <span
              key={status}
              className={`rounded px-2 py-0.5 text-xs ${STATUS_COLOR[status as QueueStatus]}`}
            >
              {STATUS_LABEL[status as QueueStatus]}: {count}
            </span>
          ))}
        </div>
      </div>

      {/* 过滤标签 */}
      <div className="flex gap-1 border-b border-border px-3 py-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`rounded px-2 py-1 text-xs transition-colors ${
              filter === f.value
                ? 'bg-primary text-text-inverse'
                : 'bg-bg-subtle text-text-secondary hover:bg-bg-hover'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 错误提示 */}
      {error && <div className="bg-error/10 px-3 py-2 text-xs text-error">{error}</div>}

      {/* 任务列表 */}
      <div className="flex-1 overflow-y-auto">
        {loading && tasks.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted">加载中...</div>
        ) : visibleTasks.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted">
            {filter === 'all' ? '队列为空' : `没有${STATUS_LABEL[filter as QueueStatus]}任务`}
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {visibleTasks.map((task) => (
              <TaskRow
                key={task.task_id}
                task={task}
                onCancel={() => cancelTask(projectPath, task.task_id)}
                onRetry={() => retryTask(projectPath, task.task_id)}
              />
            ))}
          </ul>
        )}
      </div>

      {/* 底部操作栏 */}
      <div className="flex items-center justify-between border-t border-border bg-bg-muted px-3 py-2">
        <button
          onClick={() => clearCompleted(projectPath)}
          disabled={statusSummary.completed === 0 || loading}
          className="rounded bg-bg-subtle px-2 py-1 text-xs text-text-secondary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          清除已完成 ({statusSummary.completed})
        </button>
        <button
          onClick={() => {
            void confirmDialog({
              title: '清除全部任务',
              message: '确定清除所有任务？此操作不可恢复。',
              danger: true,
            }).then((ok) => {
              if (ok) clearAll(projectPath);
            });
          }}
          disabled={totalCount === 0 || loading}
          className="rounded bg-error/15 px-2 py-1 text-xs text-error transition-colors hover:bg-error/25 disabled:cursor-not-allowed disabled:opacity-50"
        >
          清除全部
        </button>
      </div>
    </div>
  );
}

interface TaskRowProps {
  task: IngestTask;
  onCancel: () => void;
  onRetry: () => void;
}

function TaskRow({ task, onCancel, onRetry }: TaskRowProps) {
  const canCancel = task.status === 'pending' || task.status === 'failed';
  const canRetry = task.status === 'failed' && task.retry_count < task.max_retries;

  return (
    <li className="px-3 py-2 hover:bg-bg-hover">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`rounded px-1.5 py-0.5 text-ui-xs font-medium ${
                STATUS_COLOR[task.status]
              }`}
            >
              {STATUS_LABEL[task.status]}
            </span>
            <span className="truncate text-xs text-text-secondary" title={task.source_path}>
              {task.source_path.split('/').pop()}
            </span>
          </div>
          <div className="mt-1 text-ui-xs text-muted">
            <span>任务 {task.task_id}</span>
            <span className="mx-1">·</span>
            <span>创建 {formatRelativeTime(task.created_at)}</span>
            {task.retry_count > 0 && (
              <>
                <span className="mx-1">·</span>
                <span>
                  重试 {task.retry_count}/{task.max_retries}
                </span>
              </>
            )}
          </div>
          {task.error_message && (
            <div className="mt-1 truncate text-ui-xs text-error" title={task.error_message}>
              ⚠️ {task.error_message}
            </div>
          )}
        </div>

        <div className="flex shrink-0 gap-1">
          {canRetry && (
            <button
              onClick={onRetry}
              className="rounded bg-info/15 px-2 py-0.5 text-ui-xs text-info hover:bg-info/25"
              title="重试"
            >
              重试
            </button>
          )}
          {canCancel && (
            <button
              onClick={onCancel}
              className="rounded bg-bg-subtle px-2 py-0.5 text-ui-xs text-text-secondary hover:bg-bg-hover"
              title="取消"
            >
              取消
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
