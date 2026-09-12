/**
 * R17-B: memoryApi.runConsolidation 封装测试。
 *
 * mock desktopInvoke.invoke，验证通道名、统计数字归一（后端缺字段 → 0）、
 * 以及 ok=false（任务执行失败）的语义化抛错。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { memoryApi } from '../memoryApi';

describe('memoryApi.runConsolidation (R17-B)', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it('routes through scheduled_evolution_run and returns normalized stats', async () => {
    mockInvoke.mockResolvedValue({
      name: 'memory_consolidation',
      ok: true,
      result: { promoted: 3, decayed: 7, total: 10 },
    });

    await expect(memoryApi.runConsolidation()).resolves.toEqual({
      promoted: 3,
      decayed: 7,
      total: 10,
    });
    expect(mockInvoke).toHaveBeenCalledWith('scheduled_evolution_run', {
      name: 'memory_consolidation',
    });
  });

  it('coerces malformed stats to zeros', async () => {
    mockInvoke.mockResolvedValue({ ok: true, result: { promoted: 'x' } });

    await expect(memoryApi.runConsolidation()).resolves.toEqual({
      promoted: 0,
      decayed: 0,
      total: 0,
    });
  });

  it('throws a readable error when the task failed (ok=false)', async () => {
    mockInvoke.mockResolvedValue({ ok: false, result: {} });

    await expect(memoryApi.runConsolidation()).rejects.toThrow(/失败/);
  });
});
