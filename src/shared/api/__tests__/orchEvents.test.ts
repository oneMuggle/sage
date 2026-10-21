/**
 * r96: orchEvents 类型守卫单测——task/step/control/run 分类与终态判断。
 */
import { describe, expect, it } from 'vitest';

import {
  isControlEvent,
  isRunEvent,
  isStepEvent,
  isTaskEvent,
  isTerminalTaskStatus,
  type RunEvent,
} from '../orchEvents';

function event(event_type: string): RunEvent {
  return {
    event_id: 'e1',
    run_id: 'r1',
    seq: 1,
    event_type: event_type as RunEvent['event_type'],
    occurred_at: 1,
    producer: 'test',
    producer_generation: 1,
    entity: {},
    payload: {},
    visibility: 'user',
    schema_version: '1',
  };
}

describe('orchEvents type guards', () => {
  it('isTaskEvent: task.* 为真，task.step.* 与 run.* 为假', () => {
    expect(isTaskEvent(event('task.started'))).toBe(true);
    expect(isTaskEvent(event('task.progress'))).toBe(true);
    expect(isTaskEvent(event('task.step.started'))).toBe(false);
    expect(isTaskEvent(event('run.started'))).toBe(false);
  });

  it('isStepEvent: task.step.* 为真', () => {
    expect(isStepEvent(event('task.step.completed'))).toBe(true);
    expect(isStepEvent(event('task.step.failed'))).toBe(true);
    expect(isStepEvent(event('task.started'))).toBe(false);
  });

  it('isControlEvent: context/run_/approval_ 前缀为真', () => {
    expect(isControlEvent(event('task.context.appended'))).toBe(true);
    expect(isControlEvent(event('task.run_requested'))).toBe(true);
    expect(isControlEvent(event('task.approval_resolved'))).toBe(true);
    expect(isControlEvent(event('task.started'))).toBe(false);
    expect(isControlEvent(event('run.started'))).toBe(false);
  });

  it('isRunEvent: run.* 为真', () => {
    expect(isRunEvent(event('run.created'))).toBe(true);
    expect(isRunEvent(event('run.paused'))).toBe(true);
    expect(isRunEvent(event('task.planned'))).toBe(false);
  });

  it('isTerminalTaskStatus: 四终态为真', () => {
    for (const s of ['succeeded', 'completed', 'failed', 'cancelled'] as const) {
      expect(isTerminalTaskStatus(s)).toBe(true);
    }
    for (const s of ['pending', 'running', 'retrying', 'waiting_input', 'blocked'] as const) {
      expect(isTerminalTaskStatus(s)).toBe(false);
    }
  });
});
