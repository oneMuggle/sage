import { toast } from 'sonner';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { copyTextFallback, copyToClipboard } from '../clipboard';

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

function setClipboard(writeText: (text: string) => Promise<void>): void {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn(writeText) },
  });
}

afterEach(() => {
  vi.clearAllMocks();
  Reflect.deleteProperty(navigator, 'clipboard');
  Reflect.deleteProperty(document, 'execCommand');
});

describe('copyToClipboard', () => {
  it('writes through navigator.clipboard and reports success once', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    setClipboard(writeText);

    const ok = await copyToClipboard('hello', { successMessage: '已复制' });

    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
    expect(toast.success).toHaveBeenCalledWith('已复制');
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('falls back to execCommand when the Clipboard API rejects', async () => {
    setClipboard(() => Promise.reject(new Error('denied')));
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => true),
    });

    const ok = await copyToClipboard('hello');

    expect(ok).toBe(true);
    expect(document.execCommand).toHaveBeenCalledWith('copy');
  });

  it('returns false and shows the error message when both paths fail', async () => {
    setClipboard(() => Promise.reject(new Error('denied')));
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => false),
    });

    const ok = await copyToClipboard('hello', { errorMessage: '复制失败' });

    expect(ok).toBe(false);
    expect(toast.error).toHaveBeenCalledWith('复制失败');
  });

  it('stays silent when no messages are provided', async () => {
    setClipboard(() => Promise.resolve());

    await copyToClipboard('hello');

    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe('copyTextFallback', () => {
  it('removes the temporary textarea even when execCommand throws', () => {
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => {
        throw new Error('boom');
      }),
    });

    expect(copyTextFallback('hello')).toBe(false);
    expect(document.querySelectorAll('textarea')).toHaveLength(0);
  });
});
