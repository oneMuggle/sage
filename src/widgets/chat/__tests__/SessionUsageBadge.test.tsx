// src/widgets/chat/__tests__/SessionUsageBadge.test.tsx
// U14 会话用量徽章测试。
// 2026-11-25 (composer 状态条下沉): 组件改为受控展示（usage prop），
// 取数归 useSessionUsage hook —— 本测试不再 mock usageApi。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import type { SessionUsage } from '../../../shared/api/usageApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import {
  formatSessionUsageJson,
  formatSessionUsageMarkdown,
  SessionUsageBadge,
} from '../SessionUsageBadge';

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
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cache_hit_rate: 0,
    last_model: null,
    last_prompt_tokens: null,
    last_cached_tokens: null,
    last_at_ms: null,
    effective_context_window: null,
    // 2026-10-28: 性能统计字段
    avg_latency_ms: null,
    p95_latency_ms: null,
    max_latency_ms: null,
    ...overrides,
  };
}

// SessionUsageBadge 用 useI18n 拿标签，测试必须包 I18nProvider。
function renderBadge(usage: SessionUsage | null) {
  return render(
    <I18nProvider defaultLocale="zh">
      <SessionUsageBadge usage={usage} />
    </I18nProvider>,
  );
}

describe('SessionUsageBadge', () => {
  it('usage 为 null 时不渲染', () => {
    const { container } = renderBadge(null);
    expect(container.querySelector('[data-testid="session-usage-badge"]')).toBeNull();
  });

  it('有用量时显示 token 与成本', () => {
    renderBadge(
      usageFixture({
        requests: 5,
        prompt_tokens: 900,
        completion_tokens: 100,
        total_tokens: 1000,
        estimated_cost_usd: 0.0123,
      }),
    );
    expect(screen.getByTestId('session-usage-badge')).toBeInTheDocument();
    expect(screen.getByText(/1.0k tok/)).toBeInTheDocument();
    expect(screen.getByText(/· \$0\.0123/)).toBeInTheDocument();
  });

  it('会话尚无请求（requests 为 0）时不渲染', () => {
    const { container } = renderBadge(usageFixture({}));
    expect(container.querySelector('[data-testid="session-usage-badge"]')).toBeNull();
  });

  it('点击徽章展开明细弹层，Esc 收起', () => {
    renderBadge(
      usageFixture({
        requests: 3,
        prompt_tokens: 1200,
        completion_tokens: 300,
        total_tokens: 1500,
        estimated_cost_usd: 0.025,
        avg_latency_ms: 2500,
        p95_latency_ms: 4000,
        max_latency_ms: 7000,
      }),
    );
    expect(screen.queryByTestId('session-usage-popover')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('session-usage-badge'));
    const popover = screen.getByTestId('session-usage-popover');
    expect(popover.textContent).toContain('会话用量');
    expect(popover.textContent).toContain('1500');
    expect(popover.textContent).toContain('$0.0250');
    expect(popover.textContent).toContain('平均 2.5s');
    expect(popover.textContent).toContain('P95 4.0s');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('session-usage-popover')).not.toBeInTheDocument();
  });

  it('缓存交互存在时才显示命中率徽章', () => {
    const { container, rerender } = renderBadge(
      usageFixture({ requests: 1, total_tokens: 100, cache_read_tokens: 60, cache_hit_rate: 0.6 }),
    );
    expect(screen.getByTestId('session-cache-hit-rate').textContent).toContain('60%');

    rerender(
      <I18nProvider defaultLocale="zh">
        <SessionUsageBadge usage={usageFixture({ requests: 1, total_tokens: 100 })} />
      </I18nProvider>,
    );
    expect(container.querySelector('[data-testid="session-cache-hit-rate"]')).toBeNull();
  });

  it('导出会话用量 Markdown 与 JSON', () => {
    expect(formatSessionUsageMarkdown(null)).toContain('_暂无会话用量_');
    const sample = usageFixture({
      requests: 3,
      prompt_tokens: 1200,
      completion_tokens: 300,
      total_tokens: 1500,
      estimated_cost_usd: 0.025,
      cache_read_tokens: 600,
      cache_creation_tokens: 200,
      cache_hit_rate: 0.5,
    });
    const md = formatSessionUsageMarkdown(sample);
    expect(md).toContain('# 会话累计用量 — s1');
    expect(md).toContain('1.5k');
    const parsed = JSON.parse(formatSessionUsageJson(sample));
    expect(parsed.usage.total_tokens).toBe(1500);
  });
});
