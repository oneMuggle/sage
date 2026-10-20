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
  /** RD26 (round60): 排除当前正在显示的 run（避免与任务板重复）。 */
  excludeRunId?: string | null;
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

export function SessionRunHistory({ sessionId, onSelectRun, excludeRunId }: SessionRunHistoryProps) {
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<OrchRunDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

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

  const filteredRuns = runs.filter((r) => r.run_id !== excludeRunId);

  const handleCopyHistoryMd = async () => {
    /* v8 ignore start */
    const lines = [
      `# 会话历史编排 (${filteredRuns.length})`,
      `- 会话 ID: ${sessionId}`,
      '',
      ...filteredRuns.map((r) => {
        const done = r.tasks.filter((t) => t.status === 'done').length;
        const total = r.tasks.length;
        const totalTokens = r.tasks.reduce(
          (sum, t) => sum + (typeof t.used_tokens === 'number' ? t.used_tokens : 0),
          0,
        );
        return `- [${STATUS_LABEL[r.status] ?? r.status}] ${r.original_request || r.run_id} (${done}/${total} · ${totalTokens} tokens)`;
      }),
    ];
    setCopiedMd(true);
    await navigator.clipboard?.writeText(lines.join('\n'));
    setTimeout(() => setCopiedMd(false), 1500);
    /* v8 ignore stop */
  };

  const handleCopyHistoryJson = async () => {
    /* v8 ignore start */
    const payload = {
      sessionId,
      excludeRunId: excludeRunId ?? null,
      count: filteredRuns.length,
      runs: filteredRuns.map((r) => ({
        run_id: r.run_id,
        status: r.status,
        original_request: r.original_request ?? null,
        doneTasks: r.tasks.filter((t) => t.status === 'done').length,
        totalTasks: r.tasks.length,
        usedTokens: r.tasks.reduce(
          (sum, t) => sum + (typeof t.used_tokens === 'number' ? t.used_tokens : 0),
          0,
        ),
        created_at: r.created_at,
      })),
    };
    setCopiedJson(true);
    await navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    setTimeout(() => setCopiedJson(false), 1500);
    /* v8 ignore stop */
  };

  return (
    <div className="px-2 py-1" data-testid="session-run-history">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className="text-xs text-text-tertiary hover:text-text-secondary"
          onClick={() => setOpen(false)}
        >
          ▾ 历史编排
        </button>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => void handleCopyHistoryMd()}
            className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
            data-testid="session-run-history-copy-md-btn"
          >
            {copiedMd ? '已复制MD' : '复制历史MD'}
          </button>
          <button
            type="button"
            onClick={() => void handleCopyHistoryJson()}
            className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
            data-testid="session-run-history-copy-json-btn"
          >
            {copiedJson ? '已复制JSON' : '复制历史JSON'}
          </button>
        </div>
      </div>
      {loading && <div className="text-xs text-text-tertiary py-1">加载中…</div>}
      {!loading && runs.length === 0 && (
        <div className="text-xs text-text-tertiary py-1">暂无编排记录</div>
      )}
      {filteredRuns.map((run) => {
        const done = run.tasks.filter((t) => t.status === 'done').length;
        const total = run.tasks.length;
        // RD24 (round54): run 级消耗汇总 —— RT24 持久化的 used_tokens 聚合。
        const totalTokens = run.tasks.reduce(
          (sum, t) => sum + (typeof t.used_tokens === 'number' ? t.used_tokens : 0),
          0,
        );
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
            {/* RD24: 消耗统计 */}
            {totalTokens > 0 && (
              <span className="text-text-tertiary shrink-0" data-testid={`run-history-tokens-${run.run_id}`}>
                {totalTokens.toLocaleString()} tokens
              </span>
            )}
            <span className="text-text-tertiary shrink-0 text-ui-xs">
              {formatRelative(run.created_at)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
