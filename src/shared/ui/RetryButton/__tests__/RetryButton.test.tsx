import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { RetryButton } from '../RetryButton';

describe('RetryButton', () => {
  it('triggers onRetry on click', async () => {
    const onRetry = vi.fn().mockResolvedValue(undefined);
    render(<RetryButton onRetry={onRetry} />);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(onRetry).toHaveBeenCalledOnce());
  });

  it('shows attempt count after first click', async () => {
    const onRetry = vi.fn().mockResolvedValue(undefined);
    render(<RetryButton onRetry={onRetry} maxAttempts={3} />);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText('(1/3)')).toBeInTheDocument();
    });
  });

  it('disables button after maxAttempts', async () => {
    const onRetry = vi.fn().mockResolvedValue(undefined);
    render(<RetryButton onRetry={onRetry} maxAttempts={2} />);
    const btn = screen.getByRole('button');
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn).toBeDisabled();
    });
  });

  it('renders custom label', () => {
    render(<RetryButton onRetry={vi.fn()} label="再试一次" />);
    expect(screen.getByText('再试一次')).toBeInTheDocument();
  });
});
