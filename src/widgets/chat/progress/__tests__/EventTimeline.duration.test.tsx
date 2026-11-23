// @vitest-environment jsdom
/**
 * M4.1: EventTimeline 工具耗时徽标。
 *
 * canonical step 事件载荷带 duration_ms（tool_result / step.completed），
 * 时间线行内以 `· 1.2s` 形式展示；缺省或非数值时不渲染。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RunEvent } from '../../../../shared/api/orchEvents';
import { EventTimeline } from '../EventTimeline';

function evt(seq: number, type: string, payload: Record<string, unknown> = {}): RunEvent {
  return {
    event_id: `evt-${seq}`,
    seq,
    event_type: type,
    occurred_at: 1_000_000 + seq,
    producer: 'test',
    producer_generation: 1,
    entity: { run_id: 'r1', task_id: 't1', step_id: 's1' },
    payload,
  } as unknown as RunEvent;
}

describe('EventTimeline — 工具耗时 (M4.1)', () => {
  it('payload.duration_ms 渲染秒级徽标', () => {
    const events = [evt(1, 'task.step.completed', { duration_ms: 1234 })];
    render(<EventTimeline events={events} />);
    expect(screen.getByTestId('event-timeline-duration-evt-1')).toHaveTextContent('· 1.2s');
  });

  it('亚秒耗时显示毫秒', () => {
    const events = [evt(1, 'task.step.completed', { duration_ms: 850 })];
    render(<EventTimeline events={events} />);
    expect(screen.getByTestId('event-timeline-duration-evt-1')).toHaveTextContent('· 850ms');
  });

  it('缺省或非数值 duration_ms 不渲染徽标', () => {
    const events = [
      evt(1, 'task.step.started'),
      evt(2, 'task.step.completed', { duration_ms: 'fast' }),
    ];
    render(<EventTimeline events={events} />);
    expect(screen.queryByTestId('event-timeline-duration-evt-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('event-timeline-duration-evt-2')).not.toBeInTheDocument();
  });
});
