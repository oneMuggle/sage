/**
 * r93: learnApi 单元测试——显式触发后台复盘的通道与重试包装。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { learnApi } from '../learnApi';

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('learnApi.trigger', () => {
  it('传 session_id 与 prompt，返回确认信封', async () => {
    const ack = { status: 'queued', message: 'ok' };
    mockInvoke.mockResolvedValueOnce(ack);
    const r = await learnApi.trigger('s-1', '复习上下文');
    expect(mockInvoke).toHaveBeenCalledWith('trigger_learn', {
      session_id: 's-1',
      prompt: '复习上下文',
    });
    expect(r).toEqual(ack);
  });

  it('prompt 缺省为空串', async () => {
    mockInvoke.mockResolvedValueOnce({ status: 'queued', message: '' });
    await learnApi.trigger('s-1');
    expect(mockInvoke).toHaveBeenCalledWith('trigger_learn', {
      session_id: 's-1',
      prompt: '',
    });
  });

  it('拒绝经 withRetry 重试后包装（fake timers）', async () => {
    vi.useFakeTimers();
    try {
      mockInvoke.mockRejectedValue(new Error('queue down'));
      const p = learnApi.trigger('s-1');
      const settled = p.then(
        (v) => ({ ok: true as const, v }),
        (e: unknown) => ({ ok: false as const, e }),
      );
      // withRetry: 1s + 2s + 4s 退避
      await vi.advanceTimersByTimeAsync(8_000);
      const r = await settled;
      expect(r.ok).toBe(false);
      expect(mockInvoke).toHaveBeenCalledTimes(4);
    } finally {
      vi.useRealTimers();
    }
  });
});
