// src/widgets/chat/__tests__/ComposerStatusBar.test.tsx
// 2026-11-25 (composer 状态条下沉): 输入框下方状态条的渲染契约。
// 取数由 useSessionUsage 承担（其行为见 hooks/__tests__/useSessionUsage.test.tsx），
// 这里 mock 掉 hook，只验组合与空态。
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { SessionUsage } from '../../../shared/api/usageApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ComposerStatusBar } from '../ComposerStatusBar';

const mockUseSessionUsage = vi.fn<
  (sessionId: string | null) => { usage: SessionUsage | null; isLoading: boolean }
>();

vi.mock('../hooks/useSessionUsage', () => ({
  useSessionUsage: (sessionId: string | null) => mockUseSessionUsage(sessionId),
}));

function usageFixture(overrides: Partial<SessionUsage>): SessionUsage {
  return {
    session_id: 's1',
    requests: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    estimated_cost_usd: 0,
    cached_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cache_hit_rate: 0,
    last_model: null,
    last_prompt_tokens: null,
    last_cached_tokens: null,
    last_at_ms: null,
    effective_context_window: null,
    avg_latency_ms: null,
    p95_latency_ms: null,
    max_latency_ms: null,
    ...overrides,
  };
}

function renderBar(sessionId: string | null = 's1') {
  return render(
    <I18nProvider defaultLocale="zh">
      <ComposerStatusBar sessionId={sessionId} />
    </I18nProvider>,
  );
}

describe('ComposerStatusBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSessionUsage.mockReturnValue({ usage: null, isLoading: false });
  });

  it('无用量数据时不渲染（空会话由 hint 占位）', () => {
    const { container } = renderBar();
    expect(container.querySelector('[data-testid="composer-status-bar"]')).toBeNull();
  });

  it('有请求累计量时渲染用量徽章与上下文条', () => {
    mockUseSessionUsage.mockReturnValue({
      usage: usageFixture({
        requests: 2,
        total_tokens: 1000,
        last_model: 'claude-sonnet-4',
        last_prompt_tokens: 100_000,
        effective_context_window: 200_000,
      }),
      isLoading: false,
    });
    renderBar('s2');

    expect(screen.getByTestId('composer-status-bar')).toBeInTheDocument();
    expect(screen.getByTestId('session-usage-badge')).toBeInTheDocument();
    expect(screen.getByTestId('context-meter')).toBeInTheDocument();
    expect(mockUseSessionUsage).toHaveBeenCalledWith('s2');
  });

  it('只有上下文快照（无累计请求）时只渲染上下文条', () => {
    mockUseSessionUsage.mockReturnValue({
      usage: usageFixture({
        requests: 0,
        last_model: 'claude-sonnet-4',
        last_prompt_tokens: 50_000,
        effective_context_window: 200_000,
      }),
      isLoading: false,
    });
    const { container } = renderBar();

    expect(container.querySelector('[data-testid="session-usage-badge"]')).toBeNull();
    expect(screen.getByTestId('context-meter')).toBeInTheDocument();
  });

  it('上下文明细弹层向上展开并右缘对齐，避免溢出视口', () => {
    mockUseSessionUsage.mockReturnValue({
      usage: usageFixture({
        requests: 1,
        last_model: 'claude-sonnet-4',
        last_prompt_tokens: 50_000,
        effective_context_window: 200_000,
      }),
      isLoading: false,
    });
    renderBar();
    fireEvent.click(screen.getByTestId('context-meter'));
    const popover = screen.getByTestId('context-meter-popover');
    expect(popover.className).toContain('bottom-full');
    expect(popover.className).toContain('right-0');
  });
});
