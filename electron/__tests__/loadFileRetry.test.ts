// electron/__tests__/loadFileRetry.test.ts
import { describe, it, expect, vi } from 'vitest';
import {
  loadFileWithRetry,
  LOAD_FILE_RETRY_DELAY_MS,
  DEFAULT_MAX_LOAD_FILE_ATTEMPTS,
} from '../loadFileRetry';

describe('loadFileWithRetry', () => {
  it('returns on first successful attempt without delay', async () => {
    const loader = vi.fn().mockResolvedValue('ok');
    const result = await loadFileWithRetry(loader, '/path/to/index.html');
    expect(result).toBe('ok');
    expect(loader).toHaveBeenCalledTimes(1);
    expect(loader).toHaveBeenCalledWith('/path/to/index.html');
  });

  it('retries and succeeds on second attempt after one failure', async () => {
    vi.useFakeTimers();
    try {
      const err = new Error("ERR_FAILED (-2) loading 'file:///dist/index.html'");
      const loader = vi.fn().mockRejectedValueOnce(err).mockResolvedValue('ok');

      const promise = loadFileWithRetry(loader, '/dist/index.html');
      // First attempt fails synchronously in microtask; advance past the
      // retry delay so the second attempt can run and resolve.
      await vi.runAllTimersAsync();
      await expect(promise).resolves.toBe('ok');
      expect(loader).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('throws the last error when all attempts fail', async () => {
    vi.useFakeTimers();
    try {
      const err1 = new Error('ERR_FAILED (-2) attempt 1');
      const err2 = new Error('ERR_FAILED (-2) attempt 2');
      const loader = vi.fn().mockRejectedValueOnce(err1).mockRejectedValueOnce(err2);

      const promise = loadFileWithRetry(loader, '/dist/index.html', 2);
      // Attach rejection handler BEFORE draining timers — otherwise the
      // outer promise rejects in the runAllTimersAsync microtask drain,
      // and vitest's unhandledRejection detector fires before
      // `expect(...).rejects` attaches its handler below.
      const assertion = expect(promise).rejects.toThrow('ERR_FAILED (-2) attempt 2');
      await vi.runAllTimersAsync();
      await assertion;
      expect(loader).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('honors custom maxAttempts (3 attempts: 2 retries)', async () => {
    vi.useFakeTimers();
    try {
      const loader = vi
        .fn()
        .mockRejectedValueOnce(new Error('fail-1'))
        .mockRejectedValueOnce(new Error('fail-2'))
        .mockResolvedValue('ok');

      const promise = loadFileWithRetry(loader, '/dist/index.html', 3);
      await vi.runAllTimersAsync();
      await expect(promise).resolves.toBe('ok');
      expect(loader).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('throws RangeError when maxAttempts < 1', async () => {
    const loader = vi.fn();
    await expect(loadFileWithRetry(loader, 'x', 0)).rejects.toThrow(RangeError);
    await expect(loadFileWithRetry(loader, 'x', -1)).rejects.toThrow(RangeError);
    expect(loader).not.toHaveBeenCalled();
  });

  it('defaults maxAttempts to DEFAULT_MAX_LOAD_FILE_ATTEMPTS', async () => {
    vi.useFakeTimers();
    try {
      const loader = vi.fn().mockRejectedValueOnce(new Error('fail')).mockResolvedValue('ok');

      const promise = loadFileWithRetry(loader, 'x');
      await vi.runAllTimersAsync();
      await expect(promise).resolves.toBe('ok');
      expect(loader).toHaveBeenCalledTimes(DEFAULT_MAX_LOAD_FILE_ATTEMPTS);
    } finally {
      vi.useRealTimers();
    }
  });

  it('waits LOAD_FILE_RETRY_DELAY_MS between attempts', async () => {
    vi.useFakeTimers();
    try {
      const loader = vi.fn().mockRejectedValueOnce(new Error('fail')).mockResolvedValue('ok');

      const promise = loadFileWithRetry(loader, 'x');

      // Advance less than the delay — second attempt must NOT have run yet.
      await vi.advanceTimersByTimeAsync(LOAD_FILE_RETRY_DELAY_MS - 1);
      expect(loader).toHaveBeenCalledTimes(1);

      // Advance the final millisecond — second attempt now runs.
      await vi.advanceTimersByTimeAsync(1);
      await vi.runAllTimersAsync();
      await expect(promise).resolves.toBe('ok');
      expect(loader).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not delay after the final failed attempt', async () => {
    vi.useFakeTimers();
    try {
      const loader = vi
        .fn()
        .mockRejectedValueOnce(new Error('fail-1'))
        .mockRejectedValueOnce(new Error('fail-2'));

      const promise = loadFileWithRetry(loader, 'x', 2);
      // Attach rejection handler BEFORE advancing timers — see
      // "throws the last error when all attempts fail" for rationale.
      const assertion = expect(promise).rejects.toThrow('fail-2');

      // First failure triggers delay; advance past it.
      await vi.advanceTimersByTimeAsync(LOAD_FILE_RETRY_DELAY_MS);
      // Second attempt runs and rejects; the returned promise must reject
      // WITHOUT needing any further timer advancement (no delay after the
      // final attempt).
      await assertion;
      expect(loader).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
