// src/widgets/chat/progress/CurrentTaskFocus.tsx
/**
 * 焦点卡 —— 「概览」视图的主体。
 *
 * 回答一个问题：**现在到底在做什么？**
 * 编排任务树是完整清单（要滚动才看得到重点），焦点卡把"当前正在跑的
 * 那一个子任务"提到最上面，大字号展示其实时步骤，点击进入详情。
 *
 * 参考 Devin Timeline / Cursor Tasks 的 "current item pinned on top" 模式。
 */
import { useEffect, useMemo, useState } from 'react';

import type { TaskBoard } from '../../../features/send-message/useChat';

import { formatElapsed } from './progressFormat';

interface CurrentTaskFocusProps {
  board: TaskBoard | null;
  /** 打开任务详情（整面板切换）。 */
  onOpenTask: (taskId: string) => void;
}

/** 选主焦点：running 任务里 runningSince 最早的那个（最久没出结果的优先）。 */
function pickFocusTask(board: TaskBoard | null): string | null {
  if (!board) return null;
  const running = Object.values(board.statuses).filter((st) => st.status === 'running');
  if (running.length === 0) return null;
  const sorted = [...running].sort((a, b) => (a.runningSince ?? 0) - (b.runningSince ?? 0));
  return sorted[0].task_id;
}

export function CurrentTaskFocus({ board, onOpenTask }: CurrentTaskFocusProps) {
  const focusTaskId = pickFocusTask(board);

  // 有 running 任务时 1s tick 驱动实时耗时。
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!focusTaskId) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [focusTaskId]);

  const runningIds = useMemo(
    () =>
      board
        ? Object.values(board.statuses)
            .filter((st) => st.status === 'running')
            .map((st) => st.task_id)
        : [],
    [board],
  );

  if (!board || !board.dispatchedAt) return null;

  const planItem = focusTaskId ? board.plan.find((p) => p.task_id === focusTaskId) : undefined;
  const status = focusTaskId ? board.statuses[focusTaskId] : undefined;
  const live = focusTaskId ? board.live?.[focusTaskId] : undefined;

  // 无 running 任务 —— 终态 / 未开始两种收尾文案。
  if (!focusTaskId) {
    const p = board.progress;
    const total = p?.total ?? board.plan.length;
    const finished = (p?.done ?? 0) + (p?.failed ?? 0) + (p?.cancelled ?? 0) + (p?.skipped ?? 0);
    if (total > 0 && finished >= total) {
      return (
        <div
          className="rounded border border-border bg-bg-hover px-3 py-3 text-xs text-text-secondary"
          data-testid="current-task-focus"
        >
          <span className="text-primary">✓ 全部完成</span>
          <span className="ml-2 tabular-nums">
            {p?.done ?? 0}/{total} 成功
            {p && p.failed > 0 && <span className="text-error ml-1">({p.failed} 失败)</span>}
          </span>
        </div>
      );
    }
    return (
      <div
        className="rounded border border-border bg-bg-hover px-3 py-3 text-xs text-text-tertiary"
        data-testid="current-task-focus"
      >
        当前没有进行中的子任务
      </div>
    );
  }

  const elapsed = status?.runningSince ? now - status.runningSince : null;

  return (
    <div
      className="rounded border border-primary/30 bg-primary/5 px-3 py-3"
      data-testid="current-task-focus"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="px-1.5 rounded bg-primary/15 text-primary text-ui-2xs shrink-0">
              {planItem?.agent_id ?? status?.agent_id ?? 'agent'}
            </span>
            <span className="text-sm text-text truncate" title={planItem?.goal}>
              {planItem?.goal ?? status?.goal ?? ''}
            </span>
          </div>
          {live?.liveStep && (
            <div
              className="mt-1.5 text-sm text-primary font-medium animate-pulse truncate"
              data-testid="current-task-focus-step"
              title={live.liveStep}
            >
              {live.liveStep}
            </div>
          )}
          {live?.waitingApproval && (
            <div className="mt-1 text-ui-2xs text-warning">⏳ 等待审批: {live.waitingApproval}</div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          {elapsed !== null && (
            <span className="text-ui-2xs text-text-tertiary tabular-nums">
              {formatElapsed(elapsed)}
            </span>
          )}
          <button
            type="button"
            onClick={() => onOpenTask(focusTaskId)}
            className="text-ui-2xs px-2 py-0.5 border border-border rounded text-text-secondary hover:border-primary/40 hover:text-primary transition-colors"
            data-testid="current-task-focus-open"
          >
            查看详情
          </button>
        </div>
      </div>

      {runningIds.length > 1 && (
        <div className="mt-2 flex items-center gap-1.5 flex-wrap text-ui-2xs text-text-tertiary">
          <span>并行进行中 {runningIds.length} 个：</span>
          {runningIds
            .filter((id) => id !== focusTaskId)
            .map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onOpenTask(id)}
                className="px-1.5 py-0.5 border border-border rounded hover:border-primary/40 hover:text-primary transition-colors"
              >
                {board.plan.find((p) => p.task_id === id)?.agent_id ?? id}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
