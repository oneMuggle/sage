import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { PanelHeader } from '../RightPanel';

describe('PanelHeader', () => {
  describe('list view (with tab + onTabChange)', () => {
    const listProps = {
      tab: 'progress' as const,
      onTabChange: vi.fn(),
      onClose: vi.fn(),
    };

    it('renders 进度, 变更, 产物 tabs', () => {
      render(<PanelHeader {...listProps} />);
      expect(screen.getByText('进度')).toBeInTheDocument();
      expect(screen.getByText('变更')).toBeInTheDocument();
      expect(screen.getByText('产物')).toBeInTheDocument();
    });

    it('renders close button with aria-label', () => {
      render(<PanelHeader {...listProps} />);
      expect(screen.getByRole('button', { name: '关闭右侧面板' })).toBeInTheDocument();
    });

    it('clicking close button invokes onClose', () => {
      const onClose = vi.fn();
      render(<PanelHeader {...listProps} onClose={onClose} />);
      fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('viewer view (no tab props)', () => {
    it('renders close button with aria-label', () => {
      render(<PanelHeader onClose={vi.fn()} />);
      expect(screen.getByRole('button', { name: '关闭右侧面板' })).toBeInTheDocument();
    });

    it('does not render tab buttons', () => {
      render(<PanelHeader onClose={vi.fn()} />);
      expect(screen.queryByText('进度')).not.toBeInTheDocument();
      expect(screen.queryByText('变更')).not.toBeInTheDocument();
      expect(screen.queryByText('产物')).not.toBeInTheDocument();
    });

    it('clicking close button invokes onClose', () => {
      const onClose = vi.fn();
      render(<PanelHeader onClose={onClose} />);
      fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });
});

describe('PanelHeader — right-panel R2 批次 C: 产物计数徽标', () => {
  const listProps = {
    tab: 'artifacts' as const,
    onTabChange: vi.fn(),
    onClose: vi.fn(),
  };

  it('artifactCount > 0 时产物 Tab 显示 (N)', () => {
    render(<PanelHeader {...listProps} artifactCount={3} />);
    expect(screen.getByRole('button', { name: '产物 (3)' })).toBeInTheDocument();
  });

  it('artifactCount 为 0 时不显示计数', () => {
    render(<PanelHeader {...listProps} artifactCount={0} />);
    expect(screen.getByRole('button', { name: '产物' })).toBeInTheDocument();
  });
});

describe('PanelHeader — right-panel R3 批次 C: 变更计数徽标', () => {
  it('changesCount > 0 时变更 Tab 显示 (N)', () => {
    render(
      <PanelHeader
        tab="changes"
        onTabChange={vi.fn()}
        onClose={vi.fn()}
        changesCount={4}
      />,
    );
    expect(screen.getByRole('button', { name: '变更 (4)' })).toBeInTheDocument();
  });

  it('changesCount 为 0 时不显示计数', () => {
    render(
      <PanelHeader
        tab="changes"
        onTabChange={vi.fn()}
        onClose={vi.fn()}
        changesCount={0}
      />,
    );
    expect(screen.getByRole('button', { name: '变更' })).toBeInTheDocument();
  });
});
