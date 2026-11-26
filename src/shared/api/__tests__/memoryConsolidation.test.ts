/**
 * 2026-11-26: memoryApi.runEvolutionTask 触发器语义测试。
 *
 * 后端 POST /scheduled/evolution/{name}/run 改为 202 异步契约：
 * 立即返回 {name, ok, started, run}，结果经 scheduled_evolution_tasks 轮询。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { memoryApi } from '../memoryApi';

const runningSnapshot = {
  run_id: 'run-1',
  name: 'memory_reflection',
  state: 'running',
  trigger: 'manual',
  phase: 'start',
  phase_label: '准备中',
  progress: {},
  started_at: 1_700_000_000_000,
  finished_at: null,
  duration_ms: null,
  result: null,
  error: null,
};

describe('memoryApi.runEvolutionTask (async trigger)', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it('routes through scheduled_evolution_run and returns the trigger snapshot', async () => {
    mockInvoke.mockResolvedValue({
      name: 'memory_reflection',
      ok: true,
      started: true,
      run: runningSnapshot,
    });

    await expect(memoryApi.runEvolutionTask('memory_reflection')).resolves.toEqual({
      name: 'memory_reflection',
      ok: true,
      started: true,
      run: runningSnapshot,
    });
    expect(mockInvoke).toHaveBeenCalledWith('scheduled_evolution_run', {
      name: 'memory_reflection',
    });
  });

  it('marks started=false when the backend attaches to a running task', async () => {
    mockInvoke.mockResolvedValue({
      name: 'memory_consolidation',
      ok: true,
      started: false,
      run: runningSnapshot,
    });

    await expect(memoryApi.runEvolutionTask('memory_consolidation')).resolves.toMatchObject({
      started: false,
      run: runningSnapshot,
    });
  });

  it('surfaces backend detail when ok=false', async () => {
    mockInvoke.mockResolvedValue({ ok: false, detail: 'task not registered' });

    await expect(memoryApi.runEvolutionTask('memory_pruning')).rejects.toThrow(/not registered/);
  });
});
