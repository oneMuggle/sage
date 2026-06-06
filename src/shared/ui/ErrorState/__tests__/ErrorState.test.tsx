import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { ErrorState } from '../ErrorState';

describe('ErrorState', () => {
  it('renders default title and the message', () => {
    render(<ErrorState message="出大事了" />);
    expect(screen.getByText('出错了')).toBeInTheDocument();
    expect(screen.getByText('出大事了')).toBeInTheDocument();
  });

  it('renders custom title', () => {
    render(<ErrorState title="Custom" message="msg" />);
    expect(screen.getByText('Custom')).toBeInTheDocument();
  });

  it('renders retry button when onRetry provided and triggers callback', () => {
    const onRetry = vi.fn();
    render(<ErrorState message="msg" onRetry={onRetry} />);
    fireEvent.click(screen.getByText('重试'));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('does NOT render retry button when onRetry omitted', () => {
    render(<ErrorState message="msg" />);
    expect(screen.queryByText('重试')).toBeNull();
  });

  it('has role=alert and aria-live=assertive', () => {
    const { container } = render(<ErrorState message="msg" />);
    const alert = container.querySelector('[role="alert"]');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveAttribute('aria-live', 'assertive');
  });
});
