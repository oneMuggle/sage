import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WelcomeHero } from '../WelcomeHero';

// Mock useI18n
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
    locale: 'zh',
  }),
}));

describe('WelcomeHero', () => {
  it('renders avatar with correct testid', () => {
    render(<WelcomeHero />);
    const avatar = screen.getByTestId('welcome-avatar');
    expect(avatar).toBeInTheDocument();
  });

  it('renders greeting and subtitle', () => {
    render(<WelcomeHero />);
    expect(screen.getByText('welcome.hero.greeting')).toBeInTheDocument();
    expect(screen.getByText('welcome.hero.subtitle')).toBeInTheDocument();
  });

  it('renders back button when onBack prop is provided', () => {
    const onBack = vi.fn();
    render(<WelcomeHero onBack={onBack} />);
    const backButton = screen.getByRole('button', { name: /back/i });
    expect(backButton).toBeInTheDocument();
  });

  it('does not render back button when onBack prop is not provided', () => {
    render(<WelcomeHero />);
    const backButton = screen.queryByRole('button', { name: /back/i });
    expect(backButton).not.toBeInTheDocument();
  });

  it('calls onBack when back button is clicked', () => {
    const onBack = vi.fn();
    render(<WelcomeHero onBack={onBack} />);
    const backButton = screen.getByRole('button', { name: /back/i });
    backButton.click();
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
