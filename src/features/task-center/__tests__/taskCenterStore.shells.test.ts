// taskCenterStore 后台 shell 聚合测试（2026-11-07 Phase 5）
import { beforeEach, describe, expect, it } from 'vitest';

import { useTaskCenterStore } from '../taskCenterStore';

beforeEach(() => {
  useTaskCenterStore.setState({ tasks: {}, delivery: null, shellStream: null });
});

describe('registerShell', () => {
  it('registers a running shell entry', () => {
    useTaskCenterStore.getState().registerShell({
      shell_id: 'sh-1',
      command: 'pytest -q',
      status: 'running',
      exit_code: null,
      age_seconds: 42,
    });
    const entry = useTaskCenterStore.getState().tasks['shell:sh-1'];
    expect(entry).toBeDefined();
    expect(entry.kind).toBe('shell');
    expect(entry.title).toBe('pytest -q');
    expect(entry.status).toBe('running');
    expect(entry.shellId).toBe('sh-1');
    expect(entry.startedAt).toBeGreaterThan(0);
  });

  it('is idempotent and preserves startedAt', () => {
    const store = useTaskCenterStore.getState();
    store.registerShell({ shell_id: 'sh-1', command: 'a', status: 'running', age_seconds: 10 });
    const firstStart = useTaskCenterStore.getState().tasks['shell:sh-1'].startedAt;
    store.registerShell({ shell_id: 'sh-1', command: 'a', status: 'running', age_seconds: 20 });
    expect(useTaskCenterStore.getState().tasks['shell:sh-1'].startedAt).toBe(firstStart);
  });

  it('maps exit codes to terminal statuses', () => {
    const store = useTaskCenterStore.getState();
    store.registerShell({
      shell_id: 'ok',
      command: 'x',
      status: 'exited',
      exit_code: 0,
    });
    store.registerShell({
      shell_id: 'bad',
      command: 'y',
      status: 'exited',
      exit_code: 2,
    });
    store.registerShell({
      shell_id: 'unknown',
      command: 'z',
      status: 'exited',
      exit_code: null,
    });
    const tasks = useTaskCenterStore.getState().tasks;
    expect(tasks['shell:ok'].status).toBe('succeeded');
    expect(tasks['shell:bad'].status).toBe('failed');
    expect(tasks['shell:unknown'].status).toBe('failed');
    expect(tasks['shell:ok'].finishedAt).toBeGreaterThan(0);
  });

  it('updates a running entry to terminal on subsequent polls', () => {
    const store = useTaskCenterStore.getState();
    store.registerShell({ shell_id: 'sh-1', command: 'a', status: 'running' });
    store.registerShell({ shell_id: 'sh-1', command: 'a', status: 'exited', exit_code: 0 });
    expect(useTaskCenterStore.getState().tasks['shell:sh-1'].status).toBe('succeeded');
  });
});

describe('removeMissingShells', () => {
  it('removes running shells that disappeared but keeps terminal ones', () => {
    const store = useTaskCenterStore.getState();
    store.registerShell({ shell_id: 'gone', command: 'a', status: 'running' });
    store.registerShell({ shell_id: 'done', command: 'b', status: 'exited', exit_code: 0 });
    store.removeMissingShells(['done']);
    const tasks = useTaskCenterStore.getState().tasks;
    expect(tasks['shell:gone']).toBeUndefined();
    expect(tasks['shell:done']).toBeDefined();
  });
});

describe('shell stream drawer state', () => {
  it('opens and closes and is mutually exclusive with delivery drawer', () => {
    const store = useTaskCenterStore.getState();
    store.openShellStream('sh-1');
    expect(useTaskCenterStore.getState().shellStream).toBe('sh-1');

    store.openDelivery({ kind: 'lane', laneId: 'lane-1' });
    expect(useTaskCenterStore.getState().shellStream).toBeNull();
    expect(useTaskCenterStore.getState().delivery).not.toBeNull();

    store.openShellStream('sh-2');
    expect(useTaskCenterStore.getState().delivery).toBeNull();
    expect(useTaskCenterStore.getState().shellStream).toBe('sh-2');

    store.closeShellStream();
    expect(useTaskCenterStore.getState().shellStream).toBeNull();
  });
});
