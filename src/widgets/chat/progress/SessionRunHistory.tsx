// src/widgets/chat/progress/SessionRunHistory.tsx
/**
 * RD23 (round52): 会话多 run 历史浏览器。
 *
 * 可折叠面板：列出当前会话全部编排 run（最多 20 条），点击行触发
 * onSelectRun 切换到该 run 的任务板。
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { orchRunClient } from '../../../shared/api/orchRunClient';
import type { OrchRunDetail } from '../../../shared/api/orchRunClient';

interface SessionRunHistoryProps {
  sessionId: string;
  onSelectRun: (run: OrchRunDetail) => void;
}

const STATUS_LABEL: Record<string, string> = {
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  paused: '已暂停',
  draft: '草稿',
};

function formatRelative(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  return `${Math.floor(diff / 86_400_000)} 天前`;
}

export function SessionRunHistory({ sessionId, onSelectRun }: SessionRunHistoryProps) {
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<OrchRunDetail[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || runs.length > 0) return;
    setLoading(true);
    orchRunClient
      .listSessionRuns(sessionId)
      .then((resp) => setRuns(resp.runs))
      .catch(() => toast.error('历史编排加载失败'))
      .finally(() => setLoading(false));
  }, [open, sessionId, runs.length]);

  if (!open) {
    return (
      <button
        type="button"
        data-testid="run-history-toggle"
        className="text-xs text-text-tertiary hover:text-text-secondary px-2 py-0.5"
        onClick={() => setOpen(true)}
      >
        ▸ 历史编排
      </button>
    );
  }

  return (
    <div className="px-2 py-1" data-testid="session-run-history">
      <button
        type="button"
        className="text-xs text-text-tertiary hover:text-text-secondary"
        onClick={() => setOpen(false)}
      >
        ▾ 历史编排
      </button>
      {loading && <div className="text-xs text-text-tertiary py-1">加载中…</div>}
      {!loading && runs.length === 0 && (
        <div className="text-xs text-text-tertiary py-1">暂无编排记录</div>
      )}
      {runs.map((run) => {
        const done = run.tasks.filter((t) => t.status === 'done').length;
        const total = run.tasks.length;
        return (
          <button
            key={run.run_id}
            type="button"
            data-testid={`run-history-item-${run.run_id}`}
            className="w-full text-left px-2 py-1 text-xs hover:bg-bg-hover rounded flex items-center gap-2"
            onClick={() => onSelectRun(run)}
          >
            <span
              className={`shrink-0 ${
                run.status === 'completed'
                  ? 'text-green-600'
                  : run.status === 'failed'
                    ? 'text-error'
                    : 'text-text-secondary'
              }`}
            >
              {STATUS_LABEL[run.status] ?? run.status}
            </span>
            <span className="text-text-secondary truncate flex-1">
              {(run.original_request ?? '').slice(0, 60) || run.run_id}
            </span>
            {total > 0 && (
              <span className="text-text-tertiary shrink-0">
                {done}/{total}
              </span>
            )}
            <span className="text-text-tertiary shrink-0 text-[10px]">
              {formatRelative(run.created_at)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
