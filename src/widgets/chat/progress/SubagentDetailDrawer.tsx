// src/widgets/chat/progress/SubagentDetailDrawer.tsx
/**
 * Subagent detail drawer — slides in from the right when a user clicks
 * a task row in TaskTreeSection. Shows:
 * - Task header (agent, status, iteration, duration)
 * - Current step
 * - Event timeline (realtime from runControlStore)
 * - ContextInput (Phase 3) — parent agent / user steering panel,
 *   rendered only when the task is in an active (non-terminal) state.
 */

import { useMemo, useState } from 'react';

import { useRunControlStore } from '../../../entities/orchestration/runControlStore';
import { useOrchEventSubscription } from '../../../entities/orchestration/useOrchEventSubscription';
import type { RunEvent, TaskSummary } from '../../../shared/api/orchEvents';

import { ContextInput } from './ContextInput';
import { EventTimeline } from './EventTimeline';interface SubagentDetailDrawerProps {
  /** Currently visible (controlled by parent) */
  open: boolean;
  /** Called when the drawer should close */
  onClose: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  pending: '待执行',
  planned: '已规划',
  queued: '排队中',
  running: '执行中',
  retrying: '重试中',
  succeeded: '已完成',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  waiting_input: '等待输入',
  waiting_approval: '等待审批',
  blocked: '已阻塞',
};

const TERMINAL_STATUSES: ReadonlySet<TaskSummary['status']> = new Set([
  'succeeded',
  'completed',
  'failed',
  'cancelled',
]);

export function SubagentDetailDrawer({ open, onClose }: SubagentDetailDrawerProps) {
  const runs = useRunControlStore((s) => s.runs);
  const selectedRunId = useRunControlStore((s) => s.selectedRunId);
  const selectedTaskId = useRunControlStore((s) => s.selectedTaskId);
  // RD19 (round35): 聊天任务板带来的任务级统计（非编排运行视图数据）。
  const selectedTaskMeta = useRunControlStore((s) => s.selectedTaskMeta);
  const eventsByRunId = useRunControlStore((s) => s.eventsByRunId);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  // Subscribe to events when drawer is open and a run is selected
  useOrchEventSubscription(selectedRunId, open && !!selectedRunId);

  // Resolve current run + task
  const run = selectedRunId ? runs.get(selectedRunId) : undefined;
  const task: TaskSummary | undefined = useMemo(() => {
    if (!run || !selectedTaskId) return undefined;
    return run.tasks.find((t) => t.task_id === selectedTaskId);
  }, [run, selectedTaskId]);

  const taskEvents: RunEvent[] = useMemo(() => {
    const events = selectedRunId ? eventsByRunId.get(selectedRunId) ?? [] : [];
    return events.filter((event) => event.entity.task_id === selectedTaskId);
  }, [eventsByRunId, selectedRunId, selectedTaskId]);

  if (!open || !task) {
    return null;
  }

  const handleCopyDrawerMd = async () => {
    /* v8 ignore start */
    const lines = [
      `# 子代理任务详情 — ${task.agent_id ?? 'unknown'} (${task.task_id})`,
      `- 运行 ID: ${selectedRunId ?? '-'}`,
      `- 状态: ${STATUS_LABEL[task.status] ?? task.status}`,
      `- 当前步骤: ${task.current_step_id ?? '无活动步骤'}`,
      selectedTaskMeta?.used_tokens ? `- 消耗: ${selectedTaskMeta.used_tokens} tokens` : null,
      selectedTaskMeta?.duration_ms ? `- 时长: ${formatDrawerDuration(selectedTaskMeta.duration_ms)}` : null,
      task.output_preview ? `- 输出预览: ${task.output_preview}` : null,
      task.error ? `- 错误: ${task.error}` : null,
      `- 事件数: ${taskEvents.length}`,
    ].filter(Boolean) as string[];
    setCopiedMd(true);
    await navigator.clipboard?.writeText(lines.join('\n'));
    setTimeout(() => setCopiedMd(false), 1500);
    /* v8 ignore stop */
  };

  const handleCopyDrawerJson = async () => {
    /* v8 ignore start */
    const payload = {
      runId: selectedRunId ?? null,
      taskId: task.task_id,
      agentId: task.agent_id ?? 'unknown',
      status: task.status,
      currentStepId: task.current_step_id ?? null,
      usedTokens: selectedTaskMeta?.used_tokens ?? null,
      durationMs: selectedTaskMeta?.duration_ms ?? null,
      outputPreview: task.output_preview ?? null,
      error: task.error ?? null,
      eventCount: taskEvents.length,
    };
    setCopiedJson(true);
    await navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    setTimeout(() => setCopiedJson(false), 1500);
    /* v8 ignore stop */
  };

  return (
    <div
      className="absolute inset-y-0 right-0 w-96 bg-bg-primary border-l border-border-primary shadow-lg z-50 flex flex-col"
      data-testid="subagent-detail-drawer"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">
            {task.agent_id ?? 'unknown'}
          </span>
          <span className="text-xs text-text-tertiary">
            {task.task_id.slice(0, 12)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleCopyDrawerMd()}
            className="px-1.5 py-0.5 text-ui-2xs rounded border border-border-primary text-text-secondary hover:bg-bg-hover"
            data-testid="subagent-drawer-copy-md-btn"
          >
            {copiedMd ? '已复制MD' : '复制详情MD'}
          </button>
          <button
            type="button"
            onClick={() => void handleCopyDrawerJson()}
            className="px-1.5 py-0.5 text-ui-2xs rounded border border-border-primary text-text-secondary hover:bg-bg-hover"
            data-testid="subagent-drawer-copy-json-btn"
          >
            {copiedJson ? '已复制JSON' : '复制详情JSON'}
          </button>
          <span
            className={`text-xs px-2 py-0.5 rounded ${
              task.status === 'running'
                ? 'bg-primary/10 text-primary'
                : task.status === 'failed'
                  ? 'bg-error/10 text-error'
                  : task.status === 'succeeded' || task.status === 'completed'
                    ? 'bg-green-500/10 text-green-600'
                    : 'bg-bg-hover text-text-secondary'
            }`}
          >
            {STATUS_LABEL[task.status] ?? task.status}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="text-text-tertiary hover:text-text-primary"
            data-testid="drawer-close"
          >
            ✕
          </button>
        </div>
      </div>

      {/* RD19 (round35): 任务级消耗/时长统计（来源：聊天任务板终态事件，
          经 selectTask meta 传入；orch 运行视图无此数据时自然不渲染）。 */}
      {(selectedTaskMeta?.used_tokens ?? 0) > 0 ||
      (selectedTaskMeta?.duration_ms ?? 0) > 0 ? (
        <div
          className="px-4 py-2 border-b border-border-primary text-xs text-text-secondary flex gap-3"
          data-testid="drawer-task-stats"
        >
          {(selectedTaskMeta?.used_tokens ?? 0) > 0 && (
            <span>
              消耗 {selectedTaskMeta!.used_tokens!.toLocaleString()} tokens
            </span>
          )}
          {(selectedTaskMeta!.duration_ms ?? 0) > 0 && (
            <span>时长 {formatDrawerDuration(selectedTaskMeta!.duration_ms!)}</span>
          )}
        </div>
      ) : null}

      {/* Current step */}
      <div className="px-4 py-3 border-b border-border-primary">
        <div className="text-xs text-text-tertiary mb-1">当前步骤</div>
        {task.current_step_id ? (
          <div className="text-sm">{task.current_step_id.slice(0, 16)}</div>
        ) : (
          <div className="text-xs text-text-tertiary">无活动步骤</div>
        )}
        {task.output_preview && (
          <div className="mt-2 text-xs text-text-secondary truncate">
            {task.output_preview}
          </div>
        )}
        {task.error && (
          <div className="mt-2 text-xs text-error truncate" title={task.error}>
            {task.error}
          </div>
        )}
      </div>

      {/* Event timeline */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        <div className="text-xs text-text-tertiary px-2 mb-1">事件时间线</div>
        <EventTimeline events={taskEvents} />
      </div>

      {/* Steering context input — only for non-terminal tasks */}
      {selectedRunId && task.task_id && !TERMINAL_STATUSES.has(task.status) && (
        <ContextInput
          runId={selectedRunId}
          taskId={task.task_id}
          expectedTaskRevision={task.revision}
        />
      )}
    </div>
  );
}

// BU15 同款时长格式化（Drawer 局部）：<60s 秒、<1h 分秒、否则时分。
function formatDrawerDuration(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;
  if (hh > 0) return `${hh}h${String(mm).padStart(2, '0')}m`;
  return `${mm}m${String(ss).padStart(2, '0')}s`;
}
