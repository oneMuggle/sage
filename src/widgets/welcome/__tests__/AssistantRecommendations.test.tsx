import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  defaultRecommendations,
  type AssistantRecommendation,
} from '../../../entities/welcome/recommendations';
import { I18nProvider } from '../../../shared/lib/i18n';
import { AssistantRecommendations } from '../AssistantRecommendations';

function renderWithI18n(ui: React.ReactNode) {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
}

describe('AssistantRecommendations', () => {
  it('renders all provided recommendations', () => {
    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={vi.fn()} />,
    );
    // Use heading role to disambiguate title from description
    expect(screen.getByRole('button', { name: /写代码/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /搜索/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /创意/ })).toBeInTheDocument();
  });

  it('renders a card for each recommendation (count matches)', () => {
    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={vi.fn()} />,
    );
    const cards = screen.getAllByTestId('recommendation-card');
    expect(cards).toHaveLength(3);
  });

  it('calls onSelect with the clicked recommendation', () => {
    const onSelect = vi.fn();
    renderWithI18n(
      <AssistantRecommendations recommendations={defaultRecommendations} onSelect={onSelect} />,
    );
    const codeCard = screen.getAllByTestId('recommendation-card')[0]!;
    fireEvent.click(codeCard);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'code' }));
  });

  it('renders nothing when recommendations is empty', () => {
    renderWithI18n(<AssistantRecommendations recommendations={[]} onSelect={vi.fn()} />);
    expect(screen.queryByTestId('recommendation-card')).not.toBeInTheDocument();
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
});
