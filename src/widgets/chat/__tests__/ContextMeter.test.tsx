// src/widgets/chat/__tests__/ContextMeter.test.tsx
// U17 上下文占用指示器测试 — usageApi 全 mock;窗口映射走 modelWindows 真实表。
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { SessionUsage } from '../../../shared/api/usageApi';
import { ContextMeter } from '../ContextMeter';

const mockFetch = vi.fn<(sessionId: string) => Promise<SessionUsage>>();

vi.mock('../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetch(sessionId),
}));

function usageFixture(overrides: Partial<SessionUsage>): SessionUsage {
  return {
    session_id: 's1',
    requests: 1,
    prompt_tokens: 100_000,
    completion_tokens: 0,
    total_tokens: 100_000,
    estimated_cost_usd: 0,
    cached_tokens: 0,
    last_model: 'claude-sonnet-4',
    last_prompt_tokens: 100_000,
    last_cached_tokens: 0,
    last_at_ms: 1,
    ...overrides,
  };
}

describe('ContextMeter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('无会话时不渲染', () => {
    const { container } = render(<ContextMeter sessionId={null} />);
    expect(container.querySelector('[data-testid="context-meter"]')).toBeNull();
  });

  it('无 last_prompt_tokens（尚无请求）时不渲染', async () => {
    mockFetch.mockResolvedValue(usageFixture({ last_prompt_tokens: null, last_model: null }));
    const { container } = render(<ContextMeter sessionId="s1" />);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="context-meter"]')).toBeNull();
  });

  it('按模型窗口映射显示百分比 (100k/200k = 50%)', async () => {
    mockFetch.mockResolvedValue(usageFixture({}));
    render(<ContextMeter sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('context-meter')).toBeInTheDocument();
    });
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('≥90% 显示告警色文本', async () => {
    mockFetch.mockResolvedValue(
      usageFixture({ last_prompt_tokens: 190_000 }),
    );
    render(<ContextMeter sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByText('95%')).toBeInTheDocument();
    });
    expect(screen.getByText('95%').className).toContain('text-error');
  });

  it('tooltip 含 token 明细与缓存命中', async () => {
    mockFetch.mockResolvedValue(
      usageFixture({ last_cached_tokens: 40_000 }),
    );
    render(<ContextMeter sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('context-meter')).toBeInTheDocument();
    });
    const title = screen.getByTestId('context-meter').getAttribute('title') ?? '';
    expect(title).toContain('100.0k / 200.0k');
    expect(title).toContain('claude-sonnet-4');
    expect(title).toContain('40.0k');
  });
});
