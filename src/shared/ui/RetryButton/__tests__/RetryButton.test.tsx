import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import {
  RetryButton,
  formatRetryButtonAuditJson,
  formatRetryButtonAuditSnapshot,
} from '../RetryButton';

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

  it('formats audit snapshot and JSON and supports copy controls (Phase P102)', () => {
    expect(
      formatRetryButtonAuditSnapshot({
        attempts: 1,
        maxAttempts: 3,
        busy: false,
        cooldownMs: 2000,
        label: '再试一次',
      }),
    ).toBe('retryButton|attempts=1|max=3|busy=0|cooldown=2000|label=再试一次');
    expect(formatRetryButtonAuditSnapshot({})).toBe(
      'retryButton|attempts=0|max=3|busy=0|cooldown=1000|label=重试',
    );
    expect(
      JSON.parse(
        formatRetryButtonAuditJson({
          attempts: 2,
          maxAttempts: 2,
          busy: true,
          cooldownMs: 4000,
          label: '重试',
        }),
      ),
    ).toEqual({
      attempts: 2,
      maxAttempts: 2,
      busy: true,
      cooldownMs: 4000,
      label: '重试',
    });

    render(<RetryButton onRetry={vi.fn()} />);
    const snapBtn = screen.getByTestId('retry-button-copy-snapshot');
    const jsonBtn = screen.getByTestId('retry-button-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
