// 对话阅读体验第二轮 C1：生成速度统计展示。
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { GenerationStats } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { GenerationStatsBadge } from '../GenerationStatsBadge';

const renderBadge = (stats: GenerationStats | null | undefined) =>
  render(
    <I18nProvider defaultLocale="zh">
      <GenerationStatsBadge stats={stats} />
    </I18nProvider>,
  );

describe('GenerationStatsBadge', () => {
  it('summarises speed, first token and output tokens with details on hover', () => {
    renderBadge({
      input_tokens: 800,
      output_tokens: 1234,
      first_token_ms: 820,
      latency_ms: 30_000,
    });
    const badge = screen.getByTestId('generation-stats');
    expect(badge).toHaveTextContent('42.3 tok/s · 首字 0.82s · 1,234 tokens');
    const title = badge.getAttribute('title') ?? '';
    expect(title).toContain('输入：800 tokens');
    expect(title).toContain('输出：1,234 tokens');
    expect(title).toContain('首字延迟：0.82s');
    expect(title).toContain('总耗时：30.0s');
    expect(title).toContain('生成速度：42.3 tokens/秒');
  });

  it('shows the total time when there is no usage or first-token time', () => {
    renderBadge({ latency_ms: 2500 });
    expect(screen.getByTestId('generation-stats')).toHaveTextContent('耗时 2.50s');
    expect(screen.getByTestId('generation-stats')).not.toHaveTextContent('tok/s');
  });

  it('renders nothing without stats', () => {
    const { container } = renderBadge(null);
    expect(container).toBeEmptyDOMElement();
    renderBadge({});
    expect(screen.queryByTestId('generation-stats')).toBeNull();
  });
});
