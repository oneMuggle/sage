// src/shared/api/__tests__/orchRunClient.test.ts
/**
 * PR C C1 — orchRunClient.cancelRun。
 *
 * Wave 4 (2026-09-06): getRun / resumeRun 测试已删 — 历史编排记录功能移除,
 * orchRunClient 仅保留 cancelRun + updatePlan。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { orchRunClient } from '../orchRunClient';
import { formatOrchRunDetailJson, formatOrchRunDetailSummary } from '../orchRunClient';

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

  it('formats orch run detail summary and JSON (Phase P112)', () => {
    const detail = {
      run_id: 'orch-1',
      session_id: 'sess-1',
      status: 'completed',
      created_at: 1000,
      plan: [{ task_id: 't1' }],
      tasks: [{ task_id: 't1', status: 'done' }],
    };
    expect(formatOrchRunDetailSummary(detail)).toBe('orch-1 · completed · plan=1 · tasks=1');
    const parsed = JSON.parse(formatOrchRunDetailJson(detail));
    expect(parsed.runId).toBe('orch-1');
    expect(parsed.planCount).toBe(1);
    expect(parsed.taskCount).toBe(1);
  });
});
