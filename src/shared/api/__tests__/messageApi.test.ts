/**
 * r90: messageApi 单元测试——delete 的 ID 校验、通道调用与错误包装。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { messageApi } from '../messageApi';
import { ApiException } from '../utils';

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('messageApi.delete', () => {
  it('valid id invokes delete_message', async () => {
    mockInvoke.mockResolvedValueOnce(undefined);
    await expect(messageApi.delete('m-1')).resolves.toBeUndefined();
    expect(mockInvoke).toHaveBeenCalledWith('delete_message', { id: 'm-1' });
  });

  it('rejects empty id without calling invoke', async () => {
    await expect(messageApi.delete('')).rejects.toMatchObject({
      name: 'ApiException',
      code: 'VALIDATION_ERROR',
    });
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it('rejects non-string id without calling invoke', async () => {
    await expect(messageApi.delete(null as unknown as string)).rejects.toMatchObject({
      code: 'VALIDATION_ERROR',
    });
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it('validation error carries messageId details', async () => {
    const err = await messageApi.delete('').catch((e: unknown) => e as ApiException);
    expect(err).toBeInstanceOf(ApiException);
    expect((err as ApiException).details).toEqual({ messageId: '' });
  });

  it('wraps invoke rejection after retries (fake timers)', async () => {
    vi.useFakeTimers();
    try {
      mockInvoke.mockRejectedValue(new Error('db down'));
      const p = messageApi.delete('m-1');
      const settled = p.then(
        (v) => ({ ok: true as const, v }),
        (e: unknown) => ({ ok: false as const, e }),
      );
      await vi.advanceTimersByTimeAsync(8_000);
      const r = await settled;
      expect(r.ok).toBe(false);
      expect(mockInvoke).toHaveBeenCalledTimes(4);
    } finally {
      vi.useRealTimers();
    }
  });
});
