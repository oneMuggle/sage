import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useRunControlStore } from '../../../entities/orchestration/runControlStore';
import type { RunSnapshot, TaskSummary } from '../../../shared/api/orchEvents';
import { orchRunControlClient } from '../../../shared/api/orchRunControlClient';
import { steerActiveOrchTask } from '../orchSteer';

vi.mock('../../../shared/api/orchRunControlClient', () => ({
  orchRunControlClient: {
    getSnapshot: vi.fn(),
    steerTask: vi.fn(),
  },
}));

const getSnapshotMock = vi.mocked(orchRunControlClient.getSnapshot);
const steerTaskMock = vi.mocked(orchRunControlClient.steerTask);

function task(id: string, status: TaskSummary['status'], revision = 7): TaskSummary {
  return {
    task_id: id,
    agent_id: 'agent-a',
    status,
    current_step_id: null,
    output_preview: null,
    error: null,
    revision,
  };
}

function snapshot(status: RunSnapshot['status'], tasks: TaskSummary[]): RunSnapshot {
  return {
    run_id: 'run-1',
    status,
    summary: {},
    last_event_seq: 3,
    updated_at: Date.now(),
    tasks,
  };
}

describe('steerActiveOrchTask', () => {
  beforeEach(() => {
    useRunControlStore.getState().resetAll();
    getSnapshotMock.mockReset();
    steerTaskMock.mockReset();
    steerTaskMock.mockResolvedValue({ ok: true, context_id: 'ctx-1', status: 'queued' });
  });

  it('runId 为空时直接返回 false', async () => {
    await expect(steerActiveOrchTask(null, 'x')).resolves.toBe(false);
    expect(steerTaskMock).not.toHaveBeenCalled();
  });

  it('store 已有快照时优先正在运行的任务发插话', async () => {
    useRunControlStore
      .getState()
      .setRunSnapshot(snapshot('running', [task('t-wait', 'planned'), task('t-run', 'running')]));

    await expect(steerActiveOrchTask('run-1', '先跳过')).resolves.toBe(true);

    expect(steerTaskMock).toHaveBeenCalledWith({
      run_id: 'run-1',
      task_id: 't-run',
      message_type: 'additional_context',
      content: '先跳过',
      apply_mode: 'next_boundary',
      expected_task_revision: 7,
    });
    expect(getSnapshotMock).not.toHaveBeenCalled();
  });

  it('store 尚无快照时按需拉取快照并回填 store 后插话', async () => {
    getSnapshotMock.mockResolvedValue(snapshot('running', [task('t-1', 'running')]));

    await expect(steerActiveOrchTask('run-1', '补充上下文')).resolves.toBe(true);

    expect(getSnapshotMock).toHaveBeenCalledWith('run-1');
    expect(useRunControlStore.getState().runs.get('run-1')?.status).toBe('running');
    expect(steerTaskMock).toHaveBeenCalledWith(
      expect.objectContaining({ task_id: 't-1', content: '补充上下文' }),
    );
  });

  it('快照拉取失败时返回 false（调用方回退排队）', async () => {
    getSnapshotMock.mockRejectedValue(new Error('not found'));
    await expect(steerActiveOrchTask('run-1', 'x')).resolves.toBe(false);
    expect(steerTaskMock).not.toHaveBeenCalled();
  });

  it('run 已终态时返回 false', async () => {
    useRunControlStore.getState().setRunSnapshot(snapshot('completed', [task('t-1', 'succeeded')]));
    await expect(steerActiveOrchTask('run-1', 'x')).resolves.toBe(false);
    expect(steerTaskMock).not.toHaveBeenCalled();
  });

  it('steer 请求抛错时返回 false（CAS 冲突等）', async () => {
    useRunControlStore.getState().setRunSnapshot(snapshot('running', [task('t-1', 'running')]));
    steerTaskMock.mockRejectedValue(new Error('task_state_changed'));
    await expect(steerActiveOrchTask('run-1', 'x')).resolves.toBe(false);
  });
});
