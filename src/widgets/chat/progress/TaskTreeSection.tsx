// src/widgets/chat/progress/TaskTreeSection.tsx
import type { TaskBoard } from '../../../features/send-message/useChat';
// TaskStatusValue 定义在 shared/api（Task 7 已 re-export），不从 useChat import
import type { TaskStatusValue } from '../../../shared/api';

const STATUS_ICON: Record<TaskStatusValue, string> = {
  queued: '○',
  running: '◐',
  done: '✓',
  failed: '✗',
  // P0-8 (2026-08-20): cancelled 状态渲染 —— 之前未覆盖 cancel 子任务，图标
  // 退化为 undefined，TaskTreeSection 视觉上与 running 难以区分。
  cancelled: '⊘',
};

const STATUS_TITLE: Record<TaskStatusValue, string> = {
  queued: 'queued',
  running: 'running',
  done: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
};

interface TaskTreeSectionProps {
  board: TaskBoard;
  // Wave 3 H2 (2026-08-15): 运行中编排的取消入口。由上层
  // (Chat.handleCancelRun) 统一调 cancelRun + 清空 taskBoard。
  onCancel?: () => void;
}

export function TaskTreeSection({ board, onCancel }: TaskTreeSectionProps) {
  const total = board.progress?.total ?? board.plan.length;
  const doneCount =
    board.progress?.done ??
    board.plan.filter((p) => board.statuses[p.task_id]?.status === 'done').length;
  // 进度可视化 P0-2 (2026-08-12): 5 元组快照,优先从 progress 取 done/
  // running/queued/failed,后续 ProgressSection 与 TaskTreeSection 文案
  // 共享同一数据源(避免"总分不一致"的视觉冲突)。fallback 到实时聚合
  // 兼容老 run(只有 task_status 流入没 task_progress 的情况)。
  const progress = board.progress;
  const running = progress?.running ?? 0;
  const queued = progress?.queued ?? 0;
  const failed = progress?.failed ?? 0;
  const inFlight = running + queued;
  // 进度可视化 L2 修正 (2026-08-12): 全部完成时不再显示"等待结果中"，
  // 避免与下方 "完成 6/6" 自相矛盾。
  const allDone = doneCount > 0 && doneCount === total && inFlight === 0;

  return (
    <div className="space-y-1" data-testid="task-tree">
      {!allDone && (
        <div className="text-xs text-text-secondary">已拆解为 {total} 个子任务,等待结果中…</div>
      )}
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-text-secondary">
          完成 {doneCount}/{total}
          {inFlight > 0 && ` · ${inFlight} 个进行中`}
          {failed > 0 && <span className="text-error ml-1">({failed} 失败)</span>}
        </div>
        {/* Wave 3 H2 (2026-08-15): 运行中取消按钮 —— 全部完成/无 onCancel 时隐藏 */}
        {!allDone && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            data-testid="task-tree-cancel"
            className="px-2 py-1 text-xs border rounded shrink-0"
          >
            取消执行
          </button>
        )}
      </div>
      {/* P0-6 (2026-08-20): reviewer 复核结论横幅 —— pass/fail 双色 */}
      {board.review && (
        <div
          data-testid="task-review-banner"
          className={`px-2 py-1 rounded text-xs ${
            board.review.verdict === 'pass'
              ? 'bg-primary/10 text-primary'
              : 'bg-error/10 text-error'
          }`}
        >
          {board.review.verdict === 'pass'
            ? `✓ 复核通过（${board.review.assertion_count} 项断言）`
            : `⚠ 复核存疑（${board.review.assertion_count} 项断言）：${board.review.summary}`}
        </div>
      )}
      {board.plan.map((item) => {
        const st = board.statuses[item.task_id];
        const status: TaskStatusValue = st?.status ?? 'queued';
        const preview = st?.output_preview ?? st?.error ?? null;
        // P1-6 (2026-08-14): depends_on 透传 —— 有依赖的任务缩进 + 标记行。
        const dependsOn = item.depends_on ?? [];
        const hasDeps = dependsOn.length > 0;
        return (
          <div
            key={item.task_id}
            data-testid={`task-tree-item-${item.task_id}`}
            className={`flex flex-col gap-1 px-2 py-1 rounded text-xs bg-bg-hover ${
              hasDeps ? 'ml-4' : ''
            }`}
          >
            {hasDeps && (
              <div
                className="text-text-tertiary text-[10px]"
                data-testid={`task-tree-deps-${item.task_id}`}
              >
                ↳ 依赖 {dependsOn.join(', ')}
              </div>
            )}
            <div className="flex items-center gap-2">
              <span title={STATUS_TITLE[status]} className="w-4 text-center">
                {STATUS_ICON[status]}
              </span>
              <span className="px-1 rounded bg-primary/10 text-primary">{item.agent_id}</span>
              <span className="text-text-secondary flex-1">{item.goal}</span>
              {/* P0-7 (2026-08-20): 重试徽章 —— retry_count>0 才显示 */}
              {(st?.retry_count ?? 0) > 0 && (
                <span
                  data-testid={`task-tree-retry-${item.task_id}`}
                  className="text-text-tertiary text-[10px] shrink-0"
                >
                  已重试 ×{st?.retry_count}
                </span>
              )}
            </div>
            {preview && status !== 'queued' && (
              <details className="pl-6 text-muted">
                <summary>{status === 'failed' ? '错误详情' : '结果预览'}</summary>
                <pre className="mt-1 whitespace-pre-wrap">{preview}</pre>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
