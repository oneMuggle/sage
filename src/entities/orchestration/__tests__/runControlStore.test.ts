import { beforeEach, describe, expect, it } from 'vitest';

import type { RunEvent, RunSnapshot } from '../../../shared/api/orchEvents';
import { useRunControlStore } from '../runControlStore';

function event(overrides: Partial<RunEvent> = {}): RunEvent {
  return {
    event_id: `evt-${overrides.seq ?? 1}`,
    run_id: 'run-1',
    seq: 1,
    event_type: 'task.started',
    occurred_at: 1760000000000,
    producer: 'test',
    producer_generation: 1,
    entity: { task_id: 'task-1', agent_id: 'agent-1' },
    payload: {},
    visibility: 'user',
    schema_version: 'run-events@1.0',
    ...overrides,
  };
}

describe('useRunControlStore', () => {
  beforeEach(() => {
    useRunControlStore.getState().resetAll();
  });

  it('routes events to a run and updates task status', () => {
    useRunControlStore.getState().applyEvent(event());

    const run = useRunControlStore.getState().runs.get('run-1');
    expect(run?.tasks[0].status).toBe('running');
    expect(run?.last_event_seq).toBe(1);
    expect(useRunControlStore.getState().eventsByRunId.get('run-1')).toHaveLength(1);
  });

  it('deduplicates by event id and ignores sequence regressions', () => {
    const store = useRunControlStore.getState();
    store.applyEvent(event({ seq: 2, event_id: 'evt-2' }));
    store.applyEvent(event({ seq: 2, event_id: 'evt-2', event_type: 'task.failed' }));
    store.applyEvent(event({ seq: 1, event_id: 'evt-1', event_type: 'task.failed' }));

    const state = useRunControlStore.getState();
    expect(state.lastSeqByRunId.get('run-1')).toBe(2);
    expect(state.eventsByRunId.get('run-1')).toHaveLength(1);
    expect(state.runs.get('run-1')?.tasks[0].status).toBe('running');
  });

  it('marks a sequence gap for resync', () => {
    const store = useRunControlStore.getState();
    store.applyEvent(event({ seq: 1, event_id: 'evt-1' }));
    store.applyEvent(event({ seq: 3, event_id: 'evt-3' }));
    store.markGapDetected('run-1', 2, 3);

    expect(useRunControlStore.getState().resyncRequiredRunIds.has('run-1')).toBe(true);
  });

  it('uses snapshot seq and clears the resync marker', () => {
    const store = useRunControlStore.getState();
    store.markGapDetected('run-1', 2, 4);
    const snapshot: RunSnapshot = {
      run_id: 'run-1',
      status: 'running',
      summary: { running: 1 },
      last_event_seq: 4,
      updated_at: 1760000004000,
      tasks: [],
    };

    store.setRunSnapshot(snapshot);

    const state = useRunControlStore.getState();
    expect(state.lastSeqByRunId.get('run-1')).toBe(4);
    expect(state.resyncRequiredRunIds.has('run-1')).toBe(false);
  });

  it('derives run status as failed when any terminal task failed', () => {
    const store = useRunControlStore.getState();
    store.applyEvent(event({ seq: 1, event_id: 'evt-1', event_type: 'task.succeeded' }));
    store.applyEvent(event({ seq: 2, event_id: 'evt-2', event_type: 'task.failed' }));

    const run = useRunControlStore.getState().runs.get('run-1');
    expect(run?.status).toBe('failed');
  });

  it('derives run status as cancelled when no failed but some cancelled', () => {
    const store = useRunControlStore.getState();
    store.applyEvent(event({ seq: 1, event_id: 'evt-1', event_type: 'task.succeeded' }));
    store.applyEvent(event({ seq: 2, event_id: 'evt-2', event_type: 'task.cancelled' }));

    const run = useRunControlStore.getState().runs.get('run-1');
    expect(run?.status).toBe('cancelled');
  });

  it('prefers run-level events over task-derived status', () => {
    const store = useRunControlStore.getState();
    // All tasks succeed
    store.applyEvent(event({ seq: 1, event_id: 'evt-1', event_type: 'task.succeeded' }));
    // But backend emits run.failed explicitly
    store.applyEvent(event({ seq: 2, event_id: 'evt-2', event_type: 'run.failed' }));

    const run = useRunControlStore.getState().runs.get('run-1');
    expect(run?.status).toBe('failed');
  });
});
