import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { defaultRecommendations, type AssistantRecommendation } from '../../../entities/welcome/recommendations';
import { I18nProvider } from '../../../shared/lib/i18n';
import { AssistantRecommendations, formatRecommendationsJson, formatRecommendationsMarkdown } from '../AssistantRecommendations';

function renderWithI18n(ui: React.ReactNode) {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
}

describe('AssistantRecommendations', () => {
  it('renders all provided recommendations', () => {
    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={vi.fn()} />,
    );
    // Use heading role to disambiguate title from description
    expect(screen.getByRole('button', { name: /写报告/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /整理资料/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /分析表格/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /制作演示/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /写代码/ })).toBeInTheDocument();
  });

  it('renders a chip for each recommendation (count matches)', () => {
    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={vi.fn()} />,
    );
    const chips = screen.getAllByTestId('recommendation-chip');
    expect(chips).toHaveLength(5);
  });

  it('calls onSelect with the clicked recommendation', () => {
    const onSelect = vi.fn();
    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={onSelect} />,
    );
    const reportChip = screen.getAllByTestId('recommendation-chip')[0]!;
    fireEvent.click(reportChip);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'report' }));
  });

  it('renders nothing when recommendations is empty', () => {
    renderWithI18n(<AssistantRecommendations recommendations={[]} onSelect={vi.fn()} />);
    expect(screen.queryByTestId('recommendation-chip')).not.toBeInTheDocument();
  });

  it('exposes the scenario description as a tooltip', () => {
    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: '写报告' })).toHaveAttribute(
      'title',
      '明确受众、资料、格式和检查要求',
    );
  });

  it('falls back gracefully when icon name is missing from map', () => {
    const broken: AssistantRecommendation[] = [
      {
        id: 'broken',
        title: 'broken-rec',
        prompt: 'test',
        icon: 'NonExistentIcon',
        gradient: 'bg-gradient-to-r from-red-500 to-pink-500',
      },
    ];
    renderWithI18n(<AssistantRecommendations recommendations={broken} onSelect={vi.fn()} />);
    // i18n key fallback returns the key itself
    expect(screen.getByText('welcome.rec.broken.title')).toBeInTheDocument();
  });

  it('exports recommendations as Markdown and JSON', () => {
    expect(formatRecommendationsMarkdown([])).toContain('_暂无推荐任务_');
    const md = formatRecommendationsMarkdown(defaultRecommendations);
    expect(md).toContain('# 欢迎页推荐任务列表 (Assistant Recommendations)');
    expect(md).toContain('(`report`)');
    const parsed = JSON.parse(formatRecommendationsJson(defaultRecommendations));
    expect(parsed.total).toBe(5);

    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={vi.fn()} />,
    );
  });
});
