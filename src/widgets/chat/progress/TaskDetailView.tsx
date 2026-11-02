// src/widgets/chat/progress/TaskDetailView.tsx
/**
 * 任务详情视图 —— 整面板替换（不再是嵌在右栏里的小 drawer）。
 *
 * 2026-11-02 进度面板优化：
 *  - 旧 `SubagentDetailDrawer` 从 `runControlStore.runs` 解析任务，而聊天
 *    任务板（`board.runId`）的 run 从未登记进该 store → `task === undefined`
 *    → 抽屉直接 `return null`，用户"点击子agent没反应"。本视图改为直接读
 *    任务板（`board.plan` + `board.statuses` + `board.live[taskId]`），
 *    从根上修掉该 bug。
 *  - 旧抽屉是 `absolute w-96`（384px）叠在 320-560px 的右栏里，内容被裁切；
 *    本视图占满整个进度面板，实时事件流可以完整展开。
 */
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { useRunControlStore } from '../../../entities/orchestration/runControlStore';
import type { TaskBoard } from '../../../features/send-message/useChat';
import type { SubagentLiveEvent, TaskStatusValue } from '../../../shared/api';
import { orchRunClient } from '../../../shared/api/orchRunClient';
import { usePluginNames } from '../../../shared/lib/hooks/usePluginNames';
import { findPluginToolOwner } from '../../../shared/lib/permissionInsights';

import { ContextInput } from './ContextInput';
import { EventTimeline } from './EventTimeline';
import { formatDuration, formatElapsed, formatTokens } from './progressFormat';

const STATUS_ICON: Record<TaskStatusValue, string> = {
  queued: '○',
  running: '◐',
  done: '✓',
  failed: '✗',
  cancelled: '⊘',
  skipped: '↷',
};

const STATUS_LABEL: Record<TaskStatusValue, string> = {
  queued: '排队中',
  running: '执行中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
};

const TERMINAL: ReadonlySet<TaskStatusValue> = new Set(['done', 'failed', 'cancelled', 'skipped']);

/** 实时事件阶段 → 一行中文描述（可选追加插件归属后缀，R114）。 */
function describeLiveEvent(
  evt: SubagentLiveEvent,
  ownerSuffix: (toolName?: string | null) => string = () => '',
): string {
  switch (evt.phase) {
    case 'approval_requested':
      return `⏳ 等待审批: ${evt.tool_name ?? 'tool'}${ownerSuffix(evt.tool_name)}`;
    case 'approval_resolved':
      return evt.approved ? '✓ 已批准' : '✗ 已拒绝';
    case 'question':
      return '❓ 向用户提问';
    case 'failed':
      return `✗ 失败${evt.preview ? `: ${evt.preview}` : ''}`;
    case 'tool_result':
      return `👀 ${evt.tool_name ?? 'tool'}${ownerSuffix(evt.tool_name)} 返回${evt.is_error ? '（错误）' : ''}`;
    case 'tool_call':
    default:
      return `🔧 ${evt.tool_name ?? 'tool'}${ownerSuffix(evt.tool_name)}${evt.args_summary ? ` ${evt.args_summary}` : ''}`;
  }
}

interface TaskDetailViewProps {
  board: TaskBoard;
  taskId: string;
  /** 返回任务列表。 */
  onBack: () => void;
  /** 单任务重试（run 终态才可重试）。 */
  onRetryTask?: (runId: string, taskId: string) => void;
}

export function TaskDetailView({ board, taskId, onBack, onRetryTask }: TaskDetailViewProps) {
  const planItem = board.plan.find((p) => p.task_id === taskId);
  const status = board.statuses[taskId];
  const state: TaskStatusValue = status?.status ?? 'queued';
  const live = board.live?.[taskId];

  // 编排运行视图里登记过的 run 才有权威事件流 + steering 能力。
  const knownRun = useRunControlStore((s) => s.runs.get(board.runId));
  const eventsByRunId = useRunControlStore((s) => s.eventsByRunId);
  const orchEvents = useMemo(
    () => (eventsByRunId.get(board.runId) ?? []).filter((e) => e.entity.task_id === taskId),
    [eventsByRunId, board.runId, taskId],
  );

  // running 时 1s tick 驱动实时耗时。
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (state !== 'running') return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [state]);

  const [skipping, setSkipping] = useState(false);
  const handleSkip = () => {
    if (skipping) return;
    setSkipping(true);
    orchRunClient
      .cancelTask(board.runId, taskId)
      .then(() => toast.info(`已请求跳过子任务 ${taskId}`))
      .catch(() => {
        toast.error(`跳过子任务 ${taskId} 失败（已结束?）`);
        setSkipping(false);
      });
  };

  const liveEvents = live?.events ?? [];
  const currentStep = live?.liveStep ?? null;
  const output = status?.output_preview ?? null;
  const error = status?.error ?? null;
  const elapsedMs =
    state === 'running' && status?.runningSince
      ? now - status.runningSince
      : (status?.duration_ms ?? null);

  // R114: 实时行插件归属后缀 —— 子代理事件只有 tool_name，按同一名单派生。
  const hasLiveToolNames = useMemo(
    () =>
      Boolean(live?.waitingApproval) || (live?.events.some((evt) => Boolean(evt.tool_name)) ?? false),
    [live],
  );
  const pluginNames = usePluginNames(hasLiveToolNames);
  const pluginOwnerSuffix = (toolName?: string | null): string => {
    const owner = toolName ? findPluginToolOwner(toolName, pluginNames) : null;
    return owner ? `（所属插件: ${owner}）` : '';
  };

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="task-detail-view">
      {/* 头部：← 返回 + agent + 目标 + 状态 + 耗时/tokens */}
      <div className="shrink-0 border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onBack}
            data-testid="task-detail-back"
            className="text-text-secondary hover:text-text text-xs shrink-0"
          >
            ← 返回
          </button>
          <span className="px-1.5 rounded bg-primary/10 text-primary text-ui-2xs shrink-0">
            {planItem?.agent_id ?? status?.agent_id ?? 'agent'}
          </span>
          <span
            className={`text-ui-2xs px-1.5 py-0.5 rounded shrink-0 ${
              state === 'running'
                ? 'bg-primary/10 text-primary'
                : state === 'failed'
                  ? 'bg-error/10 text-error'
                  : state === 'done'
                    ? 'bg-green-500/10 text-green-600'
                    : 'bg-bg-hover text-text-secondary'
            }`}
            data-testid="task-detail-status"
          >
            {STATUS_ICON[state]} {STATUS_LABEL[state]}
          </span>
        </div>
        <div className="mt-1.5 text-sm text-text break-words">
          {planItem?.goal ?? status?.goal ?? taskId}
        </div>
        <div
          className="mt-1 flex items-center gap-2 flex-wrap text-ui-2xs text-text-tertiary"
          data-testid="task-detail-stats"
        >
          <span className="tabular-nums">任务 {taskId.slice(0, 12)}</span>
          {elapsedMs !== null && (
            <span className="tabular-nums">
              {state === 'running' ? '已运行 ' : '耗时 '}
              {state === 'running' ? formatElapsed(elapsedMs) : formatDuration(elapsedMs)}
            </span>
          )}
          {(status?.used_tokens ?? 0) > 0 && (
            <span className="tabular-nums">消耗 {formatTokens(status!.used_tokens!)}</span>
          )}
          {(status?.retry_count ?? 0) > 0 && (
            <span data-testid="task-detail-retry-count">已重试 ×{status?.retry_count}</span>
          )}
          {status?.retry_of && (
            <span className="text-primary" data-testid="task-detail-redeploy">
              重派自 {status.retry_of.slice(0, 8)}
            </span>
          )}
          {status?.adjusted && (
            <span className="text-warning" data-testid="task-detail-adjusted">
              已调整
            </span>
          )}
        </div>
        {planItem?.depends_on && planItem.depends_on.length > 0 && (
          <div className="mt-1 text-ui-2xs text-text-tertiary" data-testid="task-detail-deps">
            ↳ 依赖 {planItem.depends_on.join(', ')}
          </div>
        )}
        <div className="mt-1.5 flex items-center gap-1.5">
          {(state === 'queued' || state === 'running') && (
            <button
              type="button"
              onClick={handleSkip}
              disabled={skipping}
              data-testid="task-detail-skip"
              className="px-2 py-0.5 text-ui-2xs border border-border rounded text-text-secondary hover:text-error hover:border-error/40 disabled:opacity-50"
            >
              {skipping ? '跳过中…' : '跳过'}
            </button>
          )}
          {state === 'failed' && onRetryTask && (
            <button
              type="button"
              onClick={() => onRetryTask(board.runId, taskId)}
              data-testid="task-detail-retry"
              className="px-2 py-0.5 text-ui-2xs border border-border rounded text-text-secondary hover:text-primary hover:border-primary/40"
            >
              重试该任务
            </button>
          )}
        </div>
      </div>

      {/* 详情正文 */}
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-3">
        {/* 当前步骤 —— 大字号，这是"实时运行情况"的主答案。 */}
        <div>
          <div className="text-ui-2xs text-text-tertiary mb-1">当前步骤</div>
          <div
            className={`text-sm break-words ${
              currentStep ? 'text-primary font-medium animate-pulse' : 'text-text-tertiary'
            }`}
            data-testid="task-detail-current-step"
          >
            {currentStep ?? (state === 'running' ? '正在执行…' : '无活动步骤')}
          </div>
          {live?.waitingApproval && (
            <div className="mt-1 text-ui-2xs text-warning" data-testid="task-detail-approval">
              ⏳ 等待审批: {live.waitingApproval}
              {pluginOwnerSuffix(live.waitingApproval)}
            </div>
          )}
        </div>

        {error && (
          <div>
            <div className="text-ui-2xs text-text-tertiary mb-1">错误</div>
            <pre
              className="text-xs text-error whitespace-pre-wrap break-words bg-error/5 rounded p-2"
              data-testid="task-detail-error"
            >
              {error}
            </pre>
          </div>
        )}

        {output && (
          <div>
            <div className="text-ui-2xs text-text-tertiary mb-1">结果预览</div>
            <pre
              className="text-xs text-text-secondary whitespace-pre-wrap break-words bg-bg-hover rounded p-2"
              data-testid="task-detail-output"
            >
              {output}
            </pre>
          </div>
        )}

        {/* 实时事件流 —— 子代理的实时运行情况 */}
        <div>
          <div className="text-ui-2xs text-text-tertiary mb-1">
            实时动态（{liveEvents.length} 条）
          </div>
          {liveEvents.length === 0 ? (
            <div className="text-xs text-text-tertiary" data-testid="task-detail-events-empty">
              暂无实时事件
            </div>
          ) : (
            <ul className="space-y-0.5" data-testid="task-detail-events">
              {liveEvents.map((evt, idx) => (
                <li
                  key={`${evt.ts ?? idx}-${idx}`}
                  className="text-xs text-text-secondary flex items-start gap-2"
                >
                  <span className="text-text-tertiary shrink-0 tabular-nums w-16">
                    {evt.ts
                      ? new Date(evt.ts).toLocaleTimeString('zh-CN', {
                          hour12: false,
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })
                      : ''}
                  </span>
                  <span className="min-w-0 break-words">{describeLiveEvent(evt, pluginOwnerSuffix)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 编排运行事件时间线 —— 仅当该 run 在编排 store 中登记过 */}
        {knownRun && (
          <div>
            <div className="text-ui-2xs text-text-tertiary mb-1">事件时间线</div>
            <EventTimeline events={orchEvents} />
          </div>
        )}
      </div>

      {/* steering —— 仅编排 run 且任务未终态 */}
      {knownRun && !TERMINAL.has(state) && <ContextInput runId={board.runId} taskId={taskId} />}
    </div>
  );
}
