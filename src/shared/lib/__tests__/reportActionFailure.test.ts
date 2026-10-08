import { beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from 'sonner';

import { formatActionError, reportActionFailure } from '../reportActionFailure';

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}));

describe('reportActionFailure (U4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('formats Error instances, plain strings, and fallback values', () => {
    expect(formatActionError(new Error('network down'))).toBe('network down');
    expect(formatActionError('bad gateway')).toBe('bad gateway');
    expect(formatActionError(null, '默认错误')).toBe('默认错误');
  });

  it('logs warning and triggers toast.error by default', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const msg = reportActionFailure('保存排序失败', new Error('500 Internal'));
    expect(msg).toBe('保存排序失败：500 Internal');
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith('保存排序失败：500 Internal');
    warnSpy.mockRestore();
  });

  it('suppresses toast when notify is false', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const msg = reportActionFailure('探测失败', new Error('timeout'), { notify: false });
    expect(msg).toBe('探测失败：timeout');
    expect(toast.error).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});
