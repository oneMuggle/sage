/**
 * RecapCard 渲染测试（对标 Claude Code /recap）。
 *
 * 卡片默认展开 progress 与 nextSteps，折叠 decisions；openQuestions 有内容时
 * 默认展开。所有分段为空时对应 section 不渲染。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { RecapCard } from '../RecapCard';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

const fullRecap = {
  progress: '完成了基础功能开发，正在编写单元测试。',
  decisions: ['选择 React + TypeScript 技术栈', '采用组件化架构'],
  nextSteps: ['完成测试覆盖', '进行代码审查'],
  openQuestions: ['是否需要支持离线模式？'],
};

describe('RecapCard', () => {
  it('renders the card with title and progress', () => {
    renderWithI18n(<RecapCard recap={fullRecap} onDismiss={vi.fn()} />);

    expect(screen.getByTestId('recap-card')).toBeInTheDocument();
    expect(screen.getByText('进度总结')).toBeInTheDocument();
    expect(screen.getByText(fullRecap.progress)).toBeInTheDocument();
  });

  it('shows next steps expanded by default', () => {
    renderWithI18n(<RecapCard recap={fullRecap} onDismiss={vi.fn()} />);

    expect(screen.getByText('完成测试覆盖')).toBeInTheDocument();
    expect(screen.getByText('进行代码审查')).toBeInTheDocument();
  });

  it('collapses decisions by default and expands on toggle', () => {
    renderWithI18n(<RecapCard recap={fullRecap} onDismiss={vi.fn()} />);

    expect(screen.queryByText('选择 React + TypeScript 技术栈')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /决策/ }));

    expect(screen.getByText('选择 React + TypeScript 技术栈')).toBeInTheDocument();
  });

  it('shows open questions expanded when present', () => {
    renderWithI18n(<RecapCard recap={fullRecap} onDismiss={vi.fn()} />);

    expect(screen.getByText('是否需要支持离线模式？')).toBeInTheDocument();
  });

  it('omits sections that have no content', () => {
    renderWithI18n(
      <RecapCard
        recap={{ progress: '只有进度', decisions: [], nextSteps: [] }}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.queryByRole('button', { name: /决策/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /下一步/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /待确认问题/ })).not.toBeInTheDocument();
  });

  it('fires onDismiss when the close button is clicked', () => {
    const onDismiss = vi.fn();
    renderWithI18n(<RecapCard recap={fullRecap} onDismiss={onDismiss} />);

    fireEvent.click(screen.getByTestId('recap-card-dismiss'));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
