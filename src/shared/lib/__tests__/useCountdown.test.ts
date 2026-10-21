// src/shared/lib/__tests__/useCountdown.test.ts
// 2026-10-20: LLM 重试可视化 —— 倒计时 hook 的起止/重置/边界行为。
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useCountdown } from '../useCountdown';

describe('useCountdown', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts at the initial seconds value', () => {
    const { result } = renderHook(() => useCountdown(5));
    expect(result.current).toBe(5);
  });

  it('ticks down once per second and stops at zero', () => {
    const { result } = renderHook(() => useCountdown(3));

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(2);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(1);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(0);

    // 到 0 后停止 ticking
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current).toBe(0);
  });

  it('resets when initialSeconds changes', () => {
    const { result, rerender } = renderHook(({ seconds }) => useCountdown(seconds), {
      initialProps: { seconds: 2 },
    });

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(1);

    rerender({ seconds: 8 });
    expect(result.current).toBe(8);
  });

  it('resets when resetKey changes even if initialSeconds is identical', () => {
    const { result, rerender } = renderHook(({ seconds, key }) => useCountdown(seconds, key), {
      initialProps: { seconds: 4, key: 1 },
    });

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current).toBe(2);

    // 连续两次重试 delay 相同 —— 仅靠 initialSeconds 无法感知新一轮
    rerender({ seconds: 4, key: 2 });
    expect(result.current).toBe(4);
  });

  it('handles zero and negative delays without ticking', () => {
    const { result } = renderHook(() => useCountdown(0));
    expect(result.current).toBe(0);

    const { result: neg } = renderHook(() => useCountdown(-3));
    expect(neg.current).toBe(0);
  });

  it('rounds fractional delays up to whole seconds', () => {
    const { result } = renderHook(() => useCountdown(2.4));
    expect(result.current).toBe(3);
  });

  it('treats non-finite delays as zero instead of NaN', () => {
    const { result } = renderHook(() => useCountdown(Number.NaN));
    expect(result.current).toBe(0);

    const { result: inf } = renderHook(() => useCountdown(Number.POSITIVE_INFINITY));
    expect(inf.current).toBe(0);
  });
});
