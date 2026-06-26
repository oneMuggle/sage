/**
 * @vitest-environment jsdom
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useTypewriterPlaceholder } from '../useTypewriterPlaceholder';

describe('useTypewriterPlaceholder', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts with the first character of the first phrase', () => {
    const { result } = renderHook(() =>
      useTypewriterPlaceholder(['hello world', 'second phrase']),
    );
    expect(result.current.current).toBe('h');
    expect(result.current.isTyping).toBe(true);
  });

  it('advances one character every 50ms while typing', () => {
    const { result } = renderHook(() => useTypewriterPlaceholder(['hi']));
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(result.current.current).toBe('hi');
  });

  it('pauses after completing a phrase, then advances to next phrase', () => {
    const { result } = renderHook(() => useTypewriterPlaceholder(['ab', 'cd']));
    // 打 'ab'：t=0→'a'，t=50→'ab'
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(result.current.current).toBe('ab');
    expect(result.current.isTyping).toBe(false);
    // 暂停 1s 后切到下一条
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.current).toBe('c');
    expect(result.current.isTyping).toBe(true);
  });

  it('cycles back to the first phrase after the last one', () => {
    const { result } = renderHook(() => useTypewriterPlaceholder(['x', 'y']));
    // 推进到 'x' 完成
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(result.current.current).toBe('x');
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.current).toBe('y');
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(result.current.current).toBe('y');
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.current).toBe('x');
  });

  it('clears interval on unmount (no leaked timers)', () => {
    const clearIntervalSpy = vi.spyOn(globalThis, 'clearTimeout');
    const { unmount } = renderHook(() => useTypewriterPlaceholder(['test']));
    unmount();
    expect(clearIntervalSpy).toHaveBeenCalled();
    clearIntervalSpy.mockRestore();
  });
});
