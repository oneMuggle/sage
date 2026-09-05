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

import { useMemo } from 'react';

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
  const eventsByRunId = useRunControlStore((s) => s.eventsByRunId);

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

  return (
    <div
      className="fixed inset-y-0 right-0 w-96 bg-bg-primary border-l border-border-primary shadow-lg z-50 flex flex-col"
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
