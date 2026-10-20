// src/widgets/chat/progress/EventTimeline.tsx
/**
 * Event timeline — displays a chronological list of RunEvent objects
 * for a selected task/run. Used inside SubagentDetailDrawer.
 */

import { useState } from 'react';

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

/** RD22 (round50): 相对首事件的偏移量（+0.0s 起），便于一眼读出步骤间隔。 */
function formatOffset(ms: number): string {
  // RD25 (round56): 时钟偏移可能导致负偏移——clamp 到 0。
  const clamped = Math.max(0, ms);
  if (clamped < 1000) return `+${clamped}ms`;
  const s = clamped / 1000;
  if (s < 60) return `+${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `+${m}m${(s % 60).toFixed(0)}s`;
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
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (visible.length === 0) {
    return (
      <div className="text-xs text-text-tertiary py-2" data-testid="event-timeline-empty">
        暂无事件
      </div>
    );
  }

  const handleCopyTimelineMd = async () => {
    /* v8 ignore start */
    const base = visible[0]?.occurred_at ?? 0;
    const lines = [
      `# 事件时间线 (${visible.length}/${events.length})`,
      '',
      ...visible.map((ev) => {
        const offset = formatOffset(ev.occurred_at - base);
        const preview = extractPreview(ev.payload);
        return `- [${formatTime(ev.occurred_at)} | ${offset}] ${eventLabel(ev.event_type)}${preview ? ` — ${preview}` : ''}`;
      }),
    ];
    setCopiedMd(true);
    await navigator.clipboard?.writeText(lines.join('\n'));
    setTimeout(() => setCopiedMd(false), 1500);
    /* v8 ignore stop */
  };

  const handleCopyTimelineJson = async () => {
    /* v8 ignore start */
    const base = visible[0]?.occurred_at ?? 0;
    const payload = {
      totalEvents: events.length,
      visibleCount: visible.length,
      events: visible.map((ev) => ({
        event_id: ev.event_id,
        seq: ev.seq,
        event_type: ev.event_type,
        label: eventLabel(ev.event_type),
        occurred_at: ev.occurred_at,
        offset: formatOffset(ev.occurred_at - base),
        step_id: ev.entity.step_id ?? null,
        preview: extractPreview(ev.payload),
      })),
    };
    setCopiedJson(true);
    await navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    setTimeout(() => setCopiedJson(false), 1500);
    /* v8 ignore stop */
  };

  return (
    <div className="space-y-0.5" data-testid="event-timeline">
      <div className="flex items-center justify-end gap-1.5 px-2 pb-1">
        <button
          type="button"
          onClick={() => void handleCopyTimelineMd()}
          className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
          data-testid="event-timeline-copy-md-btn"
        >
          {copiedMd ? '已复制MD' : '复制时间线MD'}
        </button>
        <button
          type="button"
          onClick={() => void handleCopyTimelineJson()}
          className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
          data-testid="event-timeline-copy-json-btn"
        >
          {copiedJson ? '已复制JSON' : '复制时间线JSON'}
        </button>
      </div>
      {visible.map((event) => {
        const preview = extractPreview(event.payload);
        // RD22 (round50): 相对首事件的偏移量 —— 步骤间隔一目了然。
        const base = visible[0]?.occurred_at ?? event.occurred_at;
        const offset = event.occurred_at - base;
        return (
          <div
            key={event.event_id}
            data-testid={`event-timeline-item-${event.event_id}`}
            className="flex items-start gap-2 px-2 py-0.5 text-xs hover:bg-bg-hover rounded"
          >
            <span className="text-text-tertiary shrink-0 w-16 tabular-nums">
              {formatTime(event.occurred_at)}
            </span>
            <span className="text-primary shrink-0 w-12 tabular-nums text-ui-xs" data-testid={`event-timeline-offset-${event.event_id}`}>
              {formatOffset(offset)}
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
              <span className="text-text-tertiary text-ui-xs shrink-0">
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
