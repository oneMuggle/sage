// @vitest-environment jsdom
/**
 * RD22 (round50): EventTimeline 相对时间偏移。
 *
 * 验证 formatOffset 的三种区间（ms/s/m+s）与偏移列的渲染。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RunEvent } from '../../../../shared/api/orchEvents';
import { EventTimeline } from '../EventTimeline';

function evt(seq: number, occurred_at: number, type = 'task.step.started'): RunEvent {
  return {
    event_id: `evt-${seq}`,
    seq,
    event_type: type,
    occurred_at,
    producer: 'test',
    producer_generation: 1,
    entity: { run_id: 'r1', task_id: 't1', step_id: null },
    payload: {},
  } as unknown as RunEvent;
}

describe('EventTimeline — 相对时间偏移 (RD22)', () => {
  it('首事件偏移 +0ms，后续事件按毫秒差显示', () => {
    const events = [
      evt(1, 1_000_000),
      evt(2, 1_000_500), // +500ms
      evt(3, 1_002_000), // +2.0s
    ];
    render(<EventTimeline events={events} />);
    const items = screen.getAllByTestId(/^event-timeline-item-/);
    expect(items).toHaveLength(3);
    // 首事件
    expect(items[0].textContent).toContain('+0ms');
    // 第二事件 +500ms
    expect(items[1].textContent).toContain('+500ms');
    // 第三事件 +2.0s
    expect(items[2].textContent).toContain('+2.0s');
  });

  it('跨分钟偏移显示 m+s 格式', () => {
    const events = [
      evt(1, 1_000_000),
      evt(2, 1_000_000 + 90_500), // +1m30s（90.5s）
    ];
    render(<EventTimeline events={events} />);
    const items = screen.getAllByTestId(/^event-timeline-item-/);
    expect(items[1].textContent).toContain('+1m31s');
  });
});

// ============================================================================
// RD25 (round56): 负偏移防护
// ============================================================================

describe('EventTimeline — 负偏移防护 (RD25)', () => {
  it('occurred_at 早于 base → 偏移 clamp 到 +0ms', () => {
    const events = [
      evt(1, 1_002_000),
      evt(2, 1_000_500), // 早于 base（时钟偏移场景）
    ];
    render(<EventTimeline events={events} />);
    const items = screen.getAllByTestId(/^event-timeline-item-/);
    expect(items[1].textContent).toContain('+0ms');
  });
});
