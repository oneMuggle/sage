import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { LoadingState } from '../LoadingState';

describe('LoadingState', () => {
  it('renders spinner variant by default', () => {
    render(<LoadingState />);
    expect(screen.getByText('加载中…')).toBeInTheDocument();
  });

  it('renders custom label', () => {
    render(<LoadingState label="正在加载会话" />);
    expect(screen.getByText('正在加载会话')).toBeInTheDocument();
  });

  it('skeleton variant renders N rows', () => {
    const { container } = render(<LoadingState variant="skeleton" rows={5} />);
    const skeletons = container.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBe(5);
  });

  it('has role=status and aria-live=polite', () => {
    const { container } = render(<LoadingState />);
    const status = container.querySelector('[role="status"]');
    expect(status).toBeInTheDocument();
    expect(status).toHaveAttribute('aria-live', 'polite');
  });
});
