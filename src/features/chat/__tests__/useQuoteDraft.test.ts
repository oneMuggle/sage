// 对话阅读导航 A4/A5: 引用注入是一次性的追加事件。
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useQuoteDraft } from '../useQuoteDraft';

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useQuoteDraft', () => {
  it('emits a formatted append-mode quote and clears it on the next frame', () => {
    const { result } = renderHook(() => useQuoteDraft());
    expect(result.current.quotedDraft).toBeNull();

    act(() => {
      result.current.quoteText('第一行\n\n第二行');
    });
    expect(result.current.quotedDraft).toMatchObject({
      text: '> 第一行\n>\n> 第二行',
      mode: 'append',
    });

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.quotedDraft).toBeNull();
  });

  it('keeps quoteText referentially stable', () => {
    const { result, rerender } = renderHook(() => useQuoteDraft());
    const first = result.current.quoteText;
    rerender();
    expect(result.current.quoteText).toBe(first);
  });
});
