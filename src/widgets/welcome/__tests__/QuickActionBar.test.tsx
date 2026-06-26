import { render, screen, fireEvent } from '@testing-library/react';
import { MessageCircle, Star, Globe } from 'lucide-react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { QuickActionBar, type QuickAction } from '../QuickActionBar';

function renderWithI18n(ui: React.ReactNode) {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
}

const sampleActions: QuickAction[] = [
  {
    id: 'feedback',
    icon: <MessageCircle className="w-4 h-4" />,
    labelKey: 'welcome.quick.feedback',
    descKey: 'welcome.quick.feedback_desc',
    onClick: vi.fn(),
  },
  {
    id: 'github',
    icon: <Star className="w-4 h-4" />,
    labelKey: 'welcome.quick.github',
    onClick: vi.fn(),
  },
  {
    id: 'webui',
    icon: <Globe className="w-4 h-4" />,
    labelKey: 'welcome.quick.webui',
    onClick: vi.fn(),
    badge: { text: 'Unavailable', variant: 'warning' },
  },
];

describe('QuickActionBar', () => {
  it('renders one button per action', () => {
    renderWithI18n(<QuickActionBar actions={sampleActions} />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(3);
  });

  it('renders the i18n label for each action', () => {
    renderWithI18n(<QuickActionBar actions={sampleActions} />);
    expect(screen.getByText(/反馈/)).toBeInTheDocument();
    expect(screen.getByText(/GitHub/)).toBeInTheDocument();
    expect(screen.getByText(/WebUI/)).toBeInTheDocument();
  });

  it('invokes onClick when action button is clicked', () => {
    const onClick = vi.fn();
    renderWithI18n(
      <QuickActionBar actions={[{ ...sampleActions[0]!, onClick }]} />,
    );
    fireEvent.click(screen.getByText(/反馈/));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('shows badge text when badge prop is provided', () => {
    renderWithI18n(<QuickActionBar actions={sampleActions} />);
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });

  it('does not show any badge when none provided', () => {
    const noBadge: QuickAction[] = [
      {
        id: 'github',
        icon: <Star className="w-4 h-4" />,
        labelKey: 'welcome.quick.github',
        onClick: vi.fn(),
      },
    ];
    renderWithI18n(<QuickActionBar actions={noBadge} />);
    expect(screen.queryByText('Unavailable')).not.toBeInTheDocument();
  });
});
