// src/widgets/chat/hooks/__tests__/useSessionUsage.test.tsx
// 2026-11-25 (composer 状态条下沉): 取数逻辑从 SessionUsageBadge / ContextMeter
// 收敛到 useSessionUsage —— 原两份 *.active.test.tsx 的 60s 轮询门控测试合并至此。
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatStreamStore } from '../../../../features/send-message/chatStreamStore';
import type { SessionUsage } from '../../../../shared/api/usageApi';
import { useSessionUsage } from '../useSessionUsage';

const mockFetch = vi.fn<(sessionId: string) => Promise<SessionUsage>>();

vi.mock('../../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetch(sessionId),
}));

function usageFixture(sessionId: string): SessionUsage {
  return {
    session_id: sessionId,
    requests: 1,
    prompt_tokens: 1000,
    completion_tokens: 5,
    total_tokens: 1005,
    estimated_cost_usd: 0.001,
    cached_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cache_hit_rate: 0,
    last_model: 'claude-sonnet-4',
    last_prompt_tokens: 1000,
    last_cached_tokens: 0,
    last_at_ms: 1,
    effective_context_window: 200_000,
    avg_latency_ms: null,
    p95_latency_ms: null,
    max_latency_ms: null,
  };
}

describe('useSessionUsage', () => {
  let setIntervalSpy: { mock: { calls: unknown[][] }; mockRestore: () => void };
  /** testing-library 的 waitFor 自身用 50ms setInterval,只统计 60s 轮询 */
  const pollTimers = () => setIntervalSpy.mock.calls.filter(([, delay]) => delay === 60_000);

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockImplementation((sessionId) => Promise.resolve(usageFixture(sessionId)));
    useChatStreamStore.getState().resetAll();
    setIntervalSpy = vi.spyOn(window, 'setInterval');
  });

  afterEach(() => {
    setIntervalSpy.mockRestore();
    useChatStreamStore.getState().resetAll();
  });

  it('空闲会话只拉取一次，不启动 60s 轮询', async () => {
    const { result } = renderHook(() => useSessionUsage('s1'));
    await waitFor(() => expect(result.current.usage?.session_id).toBe('s1'));
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(pollTimers()).toHaveLength(0);
  });

  it('流式进行中启用 60s 轮询，流结束立即刷新并停表', async () => {
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval');
    const { result } = renderHook(() => useSessionUsage('s1'));
    await waitFor(() => expect(result.current.usage).not.toBeNull());

    act(() => {
      useChatStreamStore.getState().startStream('s1', 'm1');
    });
    await waitFor(() => expect(pollTimers()).toHaveLength(1));

    const callsBeforeEnd = mockFetch.mock.calls.length;
    act(() => {
      useChatStreamStore.getState().clearStream('s1', 'm1');
    });
    // 流末补拉一次：本轮最终的 token / 成本 / 延迟只有此刻才准确
    await waitFor(() => expect(mockFetch.mock.calls.length).toBeGreaterThan(callsBeforeEnd));
    // 轮询定时器随流结束被清掉（setInterval 调用记录是历史值，不能证明停表）
    await waitFor(() => expect(clearIntervalSpy).toHaveBeenCalled());
    clearIntervalSpy.mockRestore();
  });

  it('切换会话先清空旧值，迟到的旧会话响应不覆盖新会话', async () => {
    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useSessionUsage(id), {
      initialProps: { id: 's1' as string | null },
    });
    await waitFor(() => expect(result.current.usage?.session_id).toBe('s1'));

    let resolveS2: ((u: SessionUsage) => void) | undefined;
    const pendingS2 = new Promise<SessionUsage>((resolve) => {
      resolveS2 = resolve;
    });
    mockFetch.mockImplementation((sessionId) =>
      sessionId === 's2' ? pendingS2 : Promise.resolve(usageFixture(sessionId)),
    );

    rerender({ id: 's2' });
    await waitFor(() => expect(result.current.usage).toBeNull());
    rerender({ id: 's3' });
    await waitFor(() => expect(result.current.usage?.session_id).toBe('s3'));

    await act(async () => {
      resolveS2?.(usageFixture('s2'));
    });
    expect(result.current.usage?.session_id).toBe('s3');
  });

  it('sessionId 为 null 时不取数', () => {
    const { result } = renderHook(() => useSessionUsage(null));
    expect(result.current.usage).toBeNull();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('请求失败静默：保留上一次的值，不清空也不抛错', async () => {
    const { result } = renderHook(() => useSessionUsage('s1'));
    await waitFor(() => expect(result.current.usage?.session_id).toBe('s1'));

    mockFetch.mockRejectedValueOnce(new Error('boom'));
    act(() => {
      useChatStreamStore.getState().startStream('s1', 'm1');
    });
    act(() => {
      useChatStreamStore.getState().clearStream('s1', 'm1');
    });
    await waitFor(() => expect(mockFetch.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(result.current.usage?.session_id).toBe('s1');
    expect(result.current.isLoading).toBe(false);
  });
});
