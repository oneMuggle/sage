// ContextMeter 空闲轮询门控测试 (2026-11-05)
// 验证 60s 兜底轮询仅在流式进行中启用;空闲会话只初次拉取。
import { render, waitFor } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import type { SessionUsage } from '../../../shared/api/usageApi';
import { ContextMeter } from '../ContextMeter';

const mockFetch = vi.fn<(sessionId: string) => Promise<SessionUsage>>();

vi.mock('../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetch(sessionId),
}));

function usageFixture(): SessionUsage {
  return {
    session_id: 's1',
    requests: 1,
    prompt_tokens: 1000,
    completion_tokens: 5,
    total_tokens: 1005,
    estimated_cost_usd: 0.001,
    cached_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cache_hit_rate: 0,
    last_model: 'gpt-test',
    last_prompt_tokens: 1000,
    last_cached_tokens: 0,
    last_at_ms: null,
    effective_context_window: 8192,
    avg_latency_ms: null,
    p95_latency_ms: null,
    max_latency_ms: null,
  };
}

function renderMeter(sessionId: string | null) {
  return render(<ContextMeter sessionId={sessionId} />);
}

describe('ContextMeter 空闲轮询门控 (2026-11-05)', () => {
  let setIntervalSpy: { mock: { calls: unknown[][] }; mockRestore: () => void };
  /** testing-library 的 waitFor 自身用 50ms setInterval,只统计 60s 轮询 */
  const pollTimers = () => setIntervalSpy.mock.calls.filter(([, delay]) => delay === 60_000);

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockResolvedValue(usageFixture());
    useChatStreamStore.getState().resetAll();
    setIntervalSpy = vi.spyOn(window, 'setInterval');
  });

  afterEach(() => {
    setIntervalSpy.mockRestore();
  });

  it('空闲会话只初次拉取,不设置 60s 轮询', async () => {
    renderMeter('s1');
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(pollTimers()).toHaveLength(0);
  });

  it('流式进行中启用 60s 轮询', async () => {
    act(() => {
      useChatStreamStore.getState().startStream('s1', 'm1');
    });
    renderMeter('s1');
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(pollTimers()).toHaveLength(1);
  });
});
