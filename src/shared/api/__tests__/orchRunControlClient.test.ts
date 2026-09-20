/**
 * r89: orchRunControlClient 单元测试——snapshot / steer / cancel / approval mode。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { orchRunControlClient } from '../orchRunControlClient';

beforeEach(() => { mockInvoke.mockReset(); });

describe('orchRunControlClient', () => {
  it('getSnapshot() invokes with run_id', async () => {
    const snap = { run_id: 'r1', status: 'running', tasks: [] };
    mockInvoke.mockResolvedValueOnce(snap);
    const r = await orchRunControlClient.getSnapshot('r1');
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_get_run_snapshot', { run_id: 'r1' });
    expect(r).toEqual(snap);
  });

  it('steerTask() passes full params', async () => {
    const params = {
      run_id: 'r1', task_id: 't1',
      message_type: 'constraint' as const,
      content: 'refine the approach',
      apply_mode: 'next_boundary' as const,
    };
    mockInvoke.mockResolvedValueOnce({ ok: true, context_id: 'c1', status: 'steered' });
    const r = await orchRunControlClient.steerTask(params);
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_steer_task', expect.objectContaining(params));
    expect(r.ok).toBe(true);
  });

  it('cancelRun() passes run_id and reason', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, run_id: 'r1', status: 'cancelling' });
    const r = await orchRunControlClient.cancelRun({ run_id: 'r1', reason: 'user cancelled' });
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_cancel_run_control', expect.objectContaining({ run_id: 'r1', reason: 'user cancelled' }));
    expect(r.ok).toBe(true);
  });

  it('setApprovalMode() passes run_id and mode', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, run_id: 'r1', mode: 'auto' });
    const r = await orchRunControlClient.setApprovalMode({ run_id: 'r1', mode: 'auto' });
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_set_approval_mode', expect.objectContaining({ run_id: 'r1', mode: 'auto' }));
    expect(r.mode).toBe('auto');
  });
});
