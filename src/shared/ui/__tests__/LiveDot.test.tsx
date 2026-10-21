import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  LiveDot,
  formatLiveDotAuditJson,
  formatLiveDotAuditSnapshot,
} from '../LiveDot';

describe('LiveDot', () => {
  it('renders nothing when state is idle or omitted', () => {
    const { container, rerender } = render(<LiveDot />);
    expect(container.firstChild).toBeNull();
    rerender(<LiveDot state="idle" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders an accent pulsing dot when working', () => {
    render(<LiveDot state="working" />);
    const dot = screen.getByRole('status');
    expect(dot).toHaveClass('bg-accent');
    expect(dot).toHaveClass('animate-pulse');
  });

  it('renders a quiet non-pulsing dot when sleeping', () => {
    render(<LiveDot state="sleeping" />);
    const dot = screen.getByRole('status');
    expect(dot).toHaveClass('bg-text-muted');
    expect(dot).toHaveClass('opacity-50');
    expect(dot).not.toHaveClass('animate-pulse');
    expect(dot).not.toHaveClass('bg-accent');
  });

  it('carries a count-less, self-describing default title', () => {
    const { rerender } = render(<LiveDot state="working" />);
    expect(screen.getByRole('status')).toHaveAccessibleName('工作中');
    rerender(<LiveDot state="sleeping" />);
    expect(screen.getByRole('status')).toHaveAccessibleName('休眠中');
  });

  it('allows custom titles', () => {
    render(<LiveDot state="working" workingTitle="已连接 · 延迟 42ms" />);
    expect(screen.getByRole('status')).toHaveAttribute('title', '已连接 · 延迟 42ms');
  });

  it('merges custom className', () => {
    render(<LiveDot state="working" className="ml-2" />);
    const dot = screen.getByRole('status');
    expect(dot).toHaveClass('ml-2');
    expect(dot).toHaveClass('bg-accent');
  });

  it('formats audit snapshot and JSON and supports copy controls (Phase P102)', () => {
    expect(
      formatLiveDotAuditSnapshot({
        state: 'working',
        workingTitle: '连接中',
        sleepingTitle: '已休眠',
      }),
    ).toBe('liveDot|state=working|workingTitle=连接中|sleepingTitle=已休眠');
    expect(formatLiveDotAuditSnapshot({})).toBe(
      'liveDot|state=idle|workingTitle=工作中|sleepingTitle=休眠中',
    );
    expect(
      JSON.parse(
        formatLiveDotAuditJson({
          state: 'sleeping',
          workingTitle: '工作中',
          sleepingTitle: '休眠中',
        }),
      ),
    ).toEqual({
      state: 'sleeping',
      workingTitle: '工作中',
      sleepingTitle: '休眠中',
    });

    render(<LiveDot state="working" />);
    const snapBtn = screen.getByTestId('live-dot-copy-snapshot');
    const jsonBtn = screen.getByTestId('live-dot-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
