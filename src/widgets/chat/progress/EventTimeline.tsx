// src/widgets/chat/progress/EventTimeline.tsx
/**
 * Event timeline — displays a chronological list of RunEvent objects
 * for a selected task/run. Used inside SubagentDetailDrawer.
 */

import type { RunEvent } from '../../../shared/api/orchEvents';
import { isStepEvent, isTaskEvent } from '../../../shared/api/orchEvents';

interface EventTimelineProps {
  events: RunEvent[];
  /** Max number of events to render (oldest truncated). Default: 200 */
  maxEvents?: number;
}

/** Short human-readable label for event types */
function eventLabel(eventType: string): string {
  const map: Record<string, string> = {
    'task.planned': '已规划',
    'task.queued': '已排队',
    'task.started': '开始执行',
    'task.retrying': '重试中',
    'task.succeeded': '成功完成',
    'task.failed': '执行失败',
    'task.cancelled': '已取消',
    'task.blocked': '已阻塞',
    'task.waiting_input': '等待输入',
    'task.waiting_approval': '等待审批',
    'task.step.started': '步骤开始',
    'task.step.completed': '步骤完成',
    'task.step.failed': '步骤失败',
    'task.step.progress': '步骤进展',
  };
  return map[eventType] ?? eventType;
}

/** Icon by event category */
function eventIcon(event: RunEvent): string {
  if (isStepEvent(event)) return '◦';
  if (isTaskEvent(event)) return '●';
  if (event.event_type.startsWith('run.')) return '◆';
  return '○';
}

/** Color class by event outcome */
function eventColor(event: RunEvent): string {
  const t = event.event_type;
  if (t.includes('succeeded') || t.includes('completed')) return 'text-green-600';
  if (t.includes('failed') || t.includes('error')) return 'text-red-500';
  if (t.includes('cancelled')) return 'text-text-tertiary';
  if (t.includes('retrying') || t.includes('blocked')) return 'text-amber-500';
  if (t.includes('running') || t.includes('started')) return 'text-primary';
  return 'text-text-secondary';
}

function formatTime(msTimestamp: number): string {
  const d = new Date(msTimestamp);
  return d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function extractPreview(payload: Record<string, unknown>): string | null {
  const candidates = ['output_preview', 'error', 'reason', 'name', 'tool_name'];
  for (const key of candidates) {
    const val = payload[key];
    if (typeof val === 'string' && val.length > 0) {
      return val.length > 120 ? val.slice(0, 120) + '…' : val;
    }
  }
  return null;
}

export function EventTimeline({ events, maxEvents = 200 }: EventTimelineProps) {
  const visible = events.length > maxEvents ? events.slice(events.length - maxEvents) : events;

  if (visible.length === 0) {
    return (
      <div className="text-xs text-text-tertiary py-2" data-testid="event-timeline-empty">
        暂无事件
      </div>
    );
  }

  return (
    <div className="space-y-0.5" data-testid="event-timeline">
      {visible.map((event) => {
        const preview = extractPreview(event.payload);
        return (
          <div
            key={event.event_id}
            data-testid={`event-timeline-item-${event.event_id}`}
            className="flex items-start gap-2 px-2 py-0.5 text-xs hover:bg-bg-hover rounded"
          >
            <span className="text-text-tertiary shrink-0 w-16 tabular-nums">
              {formatTime(event.occurred_at)}
            </span>
            <span className={`shrink-0 w-3 text-center ${eventColor(event)}`}>
              {eventIcon(event)}
            </span>
            <span className={`shrink-0 ${eventColor(event)}`}>
              {eventLabel(event.event_type)}
            </span>
            {preview && (
              <span className="text-text-secondary truncate">{preview}</span>
            )}
            {event.entity.step_id && isStepEvent(event) && (
              <span className="text-text-tertiary text-[10px] shrink-0">
                #{event.entity.step_id.slice(0, 8)}
              </span>
            )}
          </div>
        );
      })}
      {events.length > maxEvents && (
        <div className="text-xs text-text-tertiary px-2 py-1">
          … 省略 {events.length - maxEvents} 条更早的事件
        </div>
      )}
    </div>
  );
}
