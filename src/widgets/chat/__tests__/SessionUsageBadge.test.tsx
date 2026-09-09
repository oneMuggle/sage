// src/widgets/chat/__tests__/SessionUsageBadge.test.tsx
// U14 会话用量徽章测试 — usageApi 全 mock。
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { SessionUsage } from '../../../shared/api/usageApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { SessionUsageBadge } from '../SessionUsageBadge';

const mockFetch = vi.fn<(sessionId: string) => Promise<SessionUsage>>();

vi.mock('../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetch(sessionId),
}));

/** U17 扩展字段后的完整 SessionUsage 夹具基座 */
function usageFixture(overrides: Partial<SessionUsage>): SessionUsage {
  return {
    session_id: 's1',
    requests: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    estimated_cost_usd: 0,
    cached_tokens: 0,
    last_model: null,
    last_prompt_tokens: null,
    last_cached_tokens: null,
    last_at_ms: null,
    ...overrides,
  };
}

// L8 PR-A (2026-09-09): SessionUsageBadge 启用 useI18n 拿 cache 标签,
// 测试必须包 I18nProvider 否则 useI18n 抛 "must be used within I18nProvider"。
function renderBadge(props: { sessionId: string | null; refreshKey?: number }) {
  return render(
    <I18nProvider defaultLocale="zh">
      <SessionUsageBadge {...props} />
    </I18nProvider>,
  );
}

describe('SessionUsageBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing without a session', () => {
    const { container } = renderBadge({ sessionId: null });
    expect(container.querySelector('[data-testid="session-usage-badge"]')).toBeNull();
  });

  it('shows token and cost when usage exists', async () => {
    mockFetch.mockResolvedValue(
      usageFixture({
        requests: 5,
        prompt_tokens: 900,
        completion_tokens: 100,
        total_tokens: 1000,
        estimated_cost_usd: 0.0123,
      }),
    );
    renderBadge({ sessionId: 's1' });
    await waitFor(() => {
      expect(screen.getByTestId('session-usage-badge')).toBeInTheDocument();
    });
    expect(screen.getByText(/1.0k tok/)).toBeInTheDocument();
    expect(screen.getByText(/· \$0\.0123/)).toBeInTheDocument();
  });

  it('hides badge when session has no usage', async () => {
    mockFetch.mockResolvedValue(usageFixture({}));
    const { container } = renderBadge({ sessionId: 's1' });
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith('s1');
    });
    expect(container.querySelector('[data-testid="session-usage-badge"]')).toBeNull();
  });
});
