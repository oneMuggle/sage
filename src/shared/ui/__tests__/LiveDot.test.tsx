import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LiveDot } from '../LiveDot';

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
});
