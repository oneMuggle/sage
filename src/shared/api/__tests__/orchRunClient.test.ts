// src/shared/api/__tests__/orchRunClient.test.ts
/**
 * orchRunClient — 编排 run API 客户端全方法测试。
 *
 * 覆盖 cancelRun / updatePlan / confirmRun / rerunFailed /
 * listSessionRuns / getRun。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { orchRunClient } from '../orchRunClient';

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('orchRunClient.cancelRun', () => {
  it('cancels a run via orchestration_cancel_run IPC', async () => {
    mockInvoke.mockResolvedValue({ ok: true, run_id: 'orch-abc', status: 'cancelled' });
    const result = await orchRunClient.cancelRun('orch-abc');
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_cancel_run', {
      run_id: 'orch-abc',
    });
    expect(result).toEqual({ ok: true, run_id: 'orch-abc', status: 'cancelled' });
  });
});

describe('orchRunClient.updatePlan', () => {
  it('sends plan items via orchestration_update_plan IPC', async () => {
    const items = [{ task_id: 't1', agent_id: 'r1', goal: 'G' }];
    mockInvoke.mockResolvedValue({ ok: true, run_id: 'orch-1', plan: items });
    const result = await orchRunClient.updatePlan('orch-1', items as never);
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_update_plan', {
      run_id: 'orch-1',
      plan: items,
    });
    expect(result).toEqual({ ok: true, run_id: 'orch-1', plan: items });
  });
});

describe('orchRunClient.confirmRun', () => {
  it('confirms a run via orchestration_confirm_run IPC', async () => {
    mockInvoke.mockResolvedValue({ ok: true });
    const result = await orchRunClient.confirmRun('orch-c1');
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_confirm_run', {
      run_id: 'orch-c1',
    });
    expect(result).toEqual({ ok: true });
  });
});

describe('orchRunClient.rerunFailed', () => {
  it('calls rerun-failed without task_ids', async () => {
    const resp = { session_id: 's1', goal: '重跑', plan_override: [] };
    mockInvoke.mockResolvedValue(resp);
    await orchRunClient.rerunFailed('orch-rf');
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_rerun_failed', {
      run_id: 'orch-rf',
    });
  });

  it('calls rerun-failed with task_ids for single-task retry (RV4)', async () => {
    const resp = { session_id: 's1', goal: '单任务重试', plan_override: [] };
    mockInvoke.mockResolvedValue(resp);
    await orchRunClient.rerunFailed('orch-rf', ['t2']);
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_rerun_failed', {
      run_id: 'orch-rf',
      task_ids: ['t2'],
    });
  });
});

describe('orchRunClient.listSessionRuns', () => {
  it('fetches session runs via orchestration_list_session_runs IPC', async () => {
    const runs = [{ run_id: 'r1', status: 'completed', tasks: [], plan: [] }];
    mockInvoke.mockResolvedValue({ runs });
    const result = await orchRunClient.listSessionRuns('sess-1');
    expect(mockInvoke).toHaveBeenCalledWith(
      'orchestration_list_session_runs',
      expect.objectContaining({ session_id: 'sess-1' }),
    );
    expect(result.runs).toEqual(runs);
  });
});

describe('orchRunClient.getRun', () => {
  it('fetches single run detail via orchestration_get_run IPC', async () => {
    const detail = {
      run_id: 'orch-gr',
      session_id: 's1',
      status: 'completed',
      plan: [],
      tasks: [{ task_id: 't1', status: 'done', used_tokens: 100 }],
    };
    mockInvoke.mockResolvedValue(detail);
    const result = await orchRunClient.getRun('orch-gr');
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_get_run', {
      run_id: 'orch-gr',
    });
    expect(result).toEqual(detail);
  });
});
