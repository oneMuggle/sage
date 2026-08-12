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

    it('renders Progress and Artifacts tabs', () => {
      render(<PanelHeader {...listProps} />);
      expect(screen.getByText('Progress')).toBeInTheDocument();
      expect(screen.getByText('Artifacts')).toBeInTheDocument();
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
      expect(screen.queryByText('Progress')).not.toBeInTheDocument();
      expect(screen.queryByText('Artifacts')).not.toBeInTheDocument();
    });

    it('clicking close button invokes onClose', () => {
      const onClose = vi.fn();
      render(<PanelHeader onClose={onClose} />);
      fireEvent.click(screen.getByRole('button', { name: '关闭右侧面板' }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });
});
