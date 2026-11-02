// src/widgets/chat/progress/StatusBar.tsx
/**
 * 进度面板顶栏 —— 常驻于 sub-tab 之上。
 *
 * 职责（2026-11-02 进度面板优化）：
 *  - 一眼可读的状态：当前 agent 状态 + 轮次
 *  - 进度条视觉（此前只有纯文本 "3/8 完成"，扫读成本高）
 *  - run 级汇总：完成数 / 进行中 / 已运行 / token 消耗
 *  - run 级操作：取消执行、自动批准开关
 *
 * 这些控件此前散落在 ProgressSection 顶行与 TaskTreeSection 里，导致
 * 「概览」视图拿不到操作入口；抽到常驻顶栏后任何视图都能操作。
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useSettings } from '../../../features/manage-settings/useSettings';
import type { TaskBoard } from '../../../features/send-message/useChat';
import { orchRunControlClient } from '../../../shared/api/orchRunControlClient';

import { formatElapsed, formatTokens } from './progressFormat';

const STATE_LABELS: Record<string, string> = {
  thinking: '思考中',
  tool_call: '调用工具',
  generating: '生成回复',
  idle: '空闲',
};

interface StatusBarProps {
  streamingState: string | null;
  isLoading: boolean;
  iteration: number;
  /** 编排任务板（null = 无编排）。 */
  board: TaskBoard | null;
  onCancel?: () => void;
}

/** run 是否已进入终态（全部任务落在 done/failed/cancelled/skipped）。 */
function isRunTerminal(board: TaskBoard): boolean {
  const total = board.progress?.total ?? board.plan.length;
  if (total === 0) return false;
  const p = board.progress;
  const finished = (p?.done ?? 0) + (p?.failed ?? 0) + (p?.cancelled ?? 0) + (p?.skipped ?? 0);
  return finished >= total;
}

export function StatusBar({
  streamingState,
  isLoading,
  iteration,
  board,
  onCancel,
}: StatusBarProps) {
  const stateLabel = streamingState ? (STATE_LABELS[streamingState] ?? streamingState) : null;
  const progress = board?.progress ?? null;
  const total = progress?.total ?? board?.plan.length ?? 0;
  const done = progress?.done ?? 0;
  const running = progress?.running ?? 0;
  const queued = progress?.queued ?? 0;
  const failed = progress?.failed ?? 0;
  const cancelled = progress?.cancelled ?? 0;
  const inFlight = running + queued;
  const dispatched = board?.dispatchedAt != null;

  // BU15/BU16 同款 1s tick —— 仅在有 in-flight 任务时启动，
  // 终态后停止定时器（避免面板无谓重渲染）。
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!board || inFlight === 0) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [board, inFlight]);

  // run 级墙钟上限提示（round25 设置键；未设置 = 0 不提示）。
  const runWallClockLimitMinutes = useSettings().settings.orch?.runWallClockLimitMinutes ?? 0;
  const runStartedAt = board?.dispatchedAt ?? null;
  const runEndedAt = board?.endedAt ?? null;
  const runElapsed = runStartedAt ? (runEndedAt ?? now) - runStartedAt : null;

  // 终态任务消耗求和 —— per-task 归因值互不重叠，求和即 run 总消耗。
  const usedTokens = board
    ? Object.values(board.statuses).reduce((sum, st) => sum + (st.used_tokens ?? 0), 0)
    : 0;

  // live-events P1: run 级审批模式开关（乐观更新，后端事件回显为准）。
  const [approvalMode, setApprovalMode] = useState<'ask' | 'auto'>(board?.approvalMode ?? 'ask');
  const [approvalPending, setApprovalPending] = useState(false);
  const toggleApprovalMode = () => {
    if (approvalPending || !board?.runId) return;
    const next = approvalMode === 'auto' ? 'ask' : 'auto';
    setApprovalPending(true);
    setApprovalMode(next); // 乐观
    orchRunControlClient
      .setApprovalMode({ run_id: board.runId, mode: next })
      .catch(() => {
        setApprovalMode(board.approvalMode ?? 'ask'); // 回滚
        toast.error('审批模式切换失败（run 已结束?）');
      })
      .finally(() => setApprovalPending(false));
  };

  const terminal = board ? isRunTerminal(board) : false;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="shrink-0 border-b border-border px-3 py-2" data-testid="progress-status-bar">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 text-xs">
          {isLoading && stateLabel && (
            <span className="text-primary font-medium shrink-0">{stateLabel}</span>
          )}
          {iteration > 0 && (
            <span className="text-text-secondary shrink-0 tabular-nums">第 {iteration} 轮</span>
          )}
          {board && !dispatched && (
            <span className="text-primary shrink-0" data-testid="plan-pending-label">
              计划待执行
            </span>
          )}
          {!board && !isLoading && !stateLabel && (
            <span className="text-muted shrink-0">等待输入...</span>
          )}
        </div>

        {/* run 级操作 —— 取消执行 / 自动批准开关 */}
        <div className="flex items-center gap-1.5 shrink-0">
          {board && dispatched && !terminal && (
            <button
              type="button"
              onClick={toggleApprovalMode}
              disabled={approvalPending}
              data-testid="task-tree-approval-mode"
              title="自动批准子代理的非危险工具调用（破坏性/可疑命令仍需确认）"
              className={`px-2 py-0.5 border rounded transition-colors disabled:opacity-50 ${
                approvalMode === 'auto'
                  ? 'border-primary/40 bg-primary/10 text-primary'
                  : 'border-border text-text-secondary'
              }`}
            >
              {approvalMode === 'auto' ? '⚡ 自动批准：开' : '⚡ 自动批准：关'}
            </button>
          )}
          {board && dispatched && !terminal && onCancel && (
            <button
              type="button"
              onClick={onCancel}
              data-testid="task-tree-cancel"
              className="px-2 py-0.5 border rounded text-xs"
            >
              取消执行
            </button>
          )}
        </div>
      </div>

      {board && dispatched && total > 0 && (
        <>
          {/* 进度条 —— 纯文本 "3/8 完成" 需要逐字扫读，进度条一眼可辨。 */}
          <div
            className="mt-2 h-1.5 w-full rounded-full bg-bg-hover overflow-hidden"
            role="progressbar"
            aria-valuenow={done}
            aria-valuemin={0}
            aria-valuemax={total}
            aria-label="编排任务进度"
            data-testid="progress-bar"
          >
            <div
              className="h-full bg-primary rounded-full transition-[width] duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="mt-1.5 flex items-center gap-2 flex-wrap text-ui-xs text-text-secondary">
            <span className="tabular-nums" data-testid="task-progress-summary">
              编排任务 {done}/{total} 完成
              {inFlight > 0 && <span> · {inFlight} 个进行中</span>}
              {failed > 0 && <span className="text-error ml-1">({failed} 失败)</span>}
              {cancelled > 0 && (
                <span className="text-text-secondary ml-1">({cancelled} 已取消)</span>
              )}
            </span>
            {runElapsed !== null && (
              <span className="tabular-nums" data-testid="task-tree-run-elapsed">
                已运行 {formatElapsed(runElapsed)}
                {runWallClockLimitMinutes > 0 ? ` · 上限 ${runWallClockLimitMinutes} 分钟` : ''}
              </span>
            )}
            {usedTokens > 0 && (
              <span className="tabular-nums">消耗 {formatTokens(usedTokens)}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
