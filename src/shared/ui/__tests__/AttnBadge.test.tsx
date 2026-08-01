import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AttnBadge } from '../AttnBadge';

describe('AttnBadge', () => {
  it('renders nothing when count is zero, negative or non-finite', () => {
    const { container, rerender } = render(<AttnBadge count={0} />);
    expect(container.firstChild).toBeNull();
    rerender(<AttnBadge count={-3} />);
    expect(container.firstChild).toBeNull();
    rerender(<AttnBadge count={Number.NaN} />);
    expect(container.firstChild).toBeNull();
    rerender(<AttnBadge count={Number.POSITIVE_INFINITY} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the count inside an accent bubble', () => {
    render(<AttnBadge count={3} />);
    const badge = screen.getByRole('status');
    expect(badge).toHaveTextContent('3');
    expect(badge).toHaveClass('bg-accent');
    expect(badge).toHaveClass('rounded-full');
  });

  it('uses a default attention title carrying the exact count', () => {
    render(<AttnBadge count={3} />);
    expect(screen.getByRole('status')).toHaveAttribute('title', '3 项待处理');
    expect(screen.getByRole('status')).toHaveAccessibleName('3 项待处理');
  });

  it('caps the display at 99+ but keeps the exact count in the title', () => {
    render(<AttnBadge count={150} />);
    const badge = screen.getByRole('status');
    expect(badge).toHaveTextContent('99+');
    expect(badge).toHaveAttribute('title', '150 项待处理');
  });

  it('renders 99 as-is (boundary)', () => {
    render(<AttnBadge count={99} />);
    expect(screen.getByRole('status')).toHaveTextContent('99');
  });

  it('honors a custom title', () => {
    render(<AttnBadge count={1} title="连接失败,请检查端点配置" />);
    expect(screen.getByRole('status')).toHaveAttribute('title', '连接失败,请检查端点配置');
  });

  it('merges custom className', () => {
    render(<AttnBadge count={1} className="ml-auto" />);
    const badge = screen.getByRole('status');
    expect(badge).toHaveClass('ml-auto');
    expect(badge).toHaveClass('bg-accent');
  });
});
