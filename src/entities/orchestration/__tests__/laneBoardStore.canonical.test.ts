// src/entities/orchestration/__tests__/laneBoardStore.canonical.test.ts
//
// live-events P2: canonical task.* 事件 → lane 卡片状态投影。
import { beforeEach, describe, expect, it } from 'vitest';

import type { RunEvent, RunEventType } from '../../../shared/api/orchEvents';
import type { Lane } from '../../../shared/api/types';
import { useLaneBoardStore } from '../laneBoardStore';

function makeLane(overrides: Partial<Lane> = {}): Lane {
  return {
    lane_id: 'lane-t1',
    task_id: 'task-t1',
    agent_id: 'researcher',
    status: 'created',
    created_at: 1,
    started_at: null,
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'default',
    metadata: {},
    ...overrides,
  };
}

function makeEvent(
  eventType: RunEventType,
  taskId: string,
  overrides: Partial<RunEvent> = {},
): RunEvent {
  return {
    event_id: `evt-${eventType}-${taskId}`,
    run_id: 'orch-test',
    seq: 1,
    event_type: eventType,
    occurred_at: 1700000000000,
    producer: 'chat-dispatcher',
    producer_generation: 0,
    entity: { task_id: taskId, agent_id: 'researcher' },
    payload: {},
    visibility: 'user',
    schema_version: 'run-events@1.0',
    ...overrides,
  };
}

function seed(lanes: Lane[]): void {
  useLaneBoardStore.setState({ lanes, boardSummary: null, error: null });
}

beforeEach(() => {
  useLaneBoardStore.setState({ lanes: [], boardSummary: null, error: null });
});

describe('laneBoardStore.applyCanonicalEvent', () => {
  it('maps lifecycle events onto the matching lane card', () => {
    seed([makeLane()]);
    const store = useLaneBoardStore.getState();

    store.applyCanonicalEvent(makeEvent('task.started', 't1'));
    expect(useLaneBoardStore.getState().lanes[0].status).toBe('running');
    expect(useLaneBoardStore.getState().lanes[0].started_at).toBe(1700000000000);

    useLaneBoardStore.getState().applyCanonicalEvent(makeEvent('task.succeeded', 't1'));
    const done = useLaneBoardStore.getState().lanes[0];
    expect(done.status).toBe('succeeded');
    expect(done.completed_at).toBe(1700000000000);
  });

  it('maps failure with error payload and waiting_approval to blocked', () => {
    seed([makeLane({ lane_id: 'lane-t2', task_id: 'task-t2' })]);
    const store = useLaneBoardStore.getState();

    store.applyCanonicalEvent(
      makeEvent('task.failed', 't2', {
        payload: { error: 'boom' },
        entity: { task_id: 't2', agent_id: 'researcher' },
      }),
    );
    const failed = useLaneBoardStore.getState().lanes[0];
    expect(failed.status).toBe('failed');
    expect(failed.error).toBe('boom');

    useLaneBoardStore.getState().applyCanonicalEvent(
      makeEvent('task.waiting_approval', 't2', {
        entity: { task_id: 't2', agent_id: 'researcher' },
      }),
    );
    expect(useLaneBoardStore.getState().lanes[0].status).toBe('blocked');
  });

  it('ignores unknown lanes and non-task events (no refresh storm)', () => {
    seed([makeLane()]);
    const before = useLaneBoardStore.getState().lanes;

    useLaneBoardStore.getState().applyCanonicalEvent(makeEvent('task.started', 't9'));
    useLaneBoardStore.getState().applyCanonicalEvent(
      makeEvent('run.started', 't1', { entity: {} }),
    );
    useLaneBoardStore.getState().applyCanonicalEvent(
      makeEvent('task.step.started', 't1', { entity: { task_id: 't1', step_id: 's1' } }),
    );
    expect(useLaneBoardStore.getState().lanes).toEqual(before);
  });

  it('maps cancellations to cancelled terminal state', () => {
    seed([makeLane({ lane_id: 'lane-t3', task_id: 'task-t3', status: 'running' })]);
    useLaneBoardStore.getState().applyCanonicalEvent(
      makeEvent('task.cancelled', 't3', {
        entity: { task_id: 't3', agent_id: 'researcher' },
      }),
    );
    expect(useLaneBoardStore.getState().lanes[0].status).toBe('cancelled');
    expect(useLaneBoardStore.getState().lanes[0].completed_at).toBe(1700000000000);
  });
});
