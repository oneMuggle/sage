import { render, screen, fireEvent } from '@testing-library/react';
import { MessageCircle, Star, Globe } from 'lucide-react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  formatQuickActionsJson,
  formatQuickActionsMarkdown,
  QuickActionBar,
  type QuickAction,
} from '../QuickActionBar';

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
    renderWithI18n(<QuickActionBar actions={[{ ...sampleActions[0]!, onClick }]} />);
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

  it('exports quick actions as Markdown and JSON', () => {
    expect(formatQuickActionsMarkdown([])).toContain('_暂无快捷操作_');
    const md = formatQuickActionsMarkdown(sampleActions);
    expect(md).toContain('# 欢迎页快捷操作栏 (Quick Action Bar)');
    expect(md).toContain('[warning: Unavailable]');
    const parsed = JSON.parse(formatQuickActionsJson(sampleActions));
    expect(parsed.total).toBe(3);

    renderWithI18n(<QuickActionBar actions={sampleActions} />);
    const mdBtn = screen.getByTestId('quick-actions-copy-md');
    const jsonBtn = screen.getByTestId('quick-actions-copy-json');
    fireEvent.click(mdBtn);
    expect(mdBtn.textContent).toContain('已复制 MD');
    fireEvent.click(jsonBtn);
    expect(jsonBtn.textContent).toContain('已复制 JSON');
  });
});
