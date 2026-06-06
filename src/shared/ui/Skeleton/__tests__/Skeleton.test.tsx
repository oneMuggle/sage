import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { Skeleton, MessageSkeleton, SessionListSkeleton } from '../index';

describe('Skeleton', () => {
  it('renders base Skeleton with role=status', () => {
    const { container } = render(<Skeleton />);
    const el = container.querySelector('[role="status"]');
    expect(el).toBeInTheDocument();
    expect(el).toHaveAttribute('aria-busy', 'true');
  });

  it('renders circle variant with rounded-full class', () => {
    const { container } = render(<Skeleton circle />);
    expect(container.querySelector('.rounded-full')).toBeInTheDocument();
  });

  it('renders square variant with rounded (not rounded-full) class', () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelector('.rounded')).toBeInTheDocument();
    expect(container.querySelector('.rounded-full')).toBeNull();
  });

  it('applies custom width/height via style', () => {
    const { container } = render(<Skeleton width="50%" height="2rem" />);
    const el = container.querySelector('[role="status"]') as HTMLElement;
    expect(el.style.width).toBe('50%');
    expect(el.style.height).toBe('2rem');
  });
});

describe('MessageSkeleton', () => {
  it('renders with aria-label=加载消息中', () => {
    render(<MessageSkeleton />);
    expect(screen.getByLabelText('加载消息中')).toBeInTheDocument();
  });

  it('has 5 skeleton elements (1 avatar + 4 text)', () => {
    const { container } = render(<MessageSkeleton />);
    expect(container.querySelectorAll('.animate-pulse').length).toBe(5);
  });
});

describe('SessionListSkeleton', () => {
  it('renders default 5 rows × 3 skeletons each = 15', () => {
    const { container } = render(<SessionListSkeleton />);
    expect(container.querySelectorAll('.animate-pulse').length).toBe(15);
  });

  it('renders custom rows count (3 rows × 3 = 9)', () => {
    const { container } = render(<SessionListSkeleton rows={3} />);
    expect(container.querySelectorAll('.animate-pulse').length).toBe(9);
  });
});
