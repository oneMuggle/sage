// src/shared/api/__tests__/orchRunClient.test.ts
/**
 * PR C C1 — orchRunClient.cancelRun + detail/resume original_request 字段。
 *
 * RED 证明：cancelRun 尚未实现 → 调用抛 TypeError（类型层面 tsc 亦报
 * TS2339）。GREEN 后断言：
 *   - cancelRun → invoke('orchestration_cancel_run', { run_id })
 *   - getRun/resumeRun 透传后端 original_request（恢复流逐字回填依赖它）
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

describe('orchRunClient.cancelRun (PR C C1)', () => {
  it('cancels a run via orchestration_cancel_run IPC', async () => {
    mockInvoke.mockResolvedValue({ ok: true, run_id: 'orch-abc', status: 'cancelled' });
    const result = await orchRunClient.cancelRun('orch-abc');
    expect(mockInvoke).toHaveBeenCalledWith('orchestration_cancel_run', {
      run_id: 'orch-abc',
    });
    expect(result).toEqual({ ok: true, run_id: 'orch-abc', status: 'cancelled' });
  });
});

describe('orchRunClient detail/resume original_request (PR C C1)', () => {
  it('getRun surfaces original_request from backend', async () => {
    mockInvoke.mockResolvedValue({
      run_id: 'orch-abc',
      session_id: 's',
      status: 'cancelled',
      original_request: '恢复原计划',
      plan: [],
      tasks: [],
    });
    const detail = await orchRunClient.getRun('orch-abc');
    expect(detail.original_request).toBe('恢复原计划');
  });

  it('resumeRun surfaces original_request from backend', async () => {
    mockInvoke.mockResolvedValue({
      ok: true,
      new_run_id: 'orch-def',
      session_id: 's',
      original_request: '恢复原计划',
      plan: [],
    });
    const resume = await orchRunClient.resumeRun('orch-abc');
    expect(resume.original_request).toBe('恢复原计划');
  });
});
