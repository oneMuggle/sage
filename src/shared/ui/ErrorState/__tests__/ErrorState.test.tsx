import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import {
  ErrorState,
  formatErrorStateAuditJson,
  formatErrorStateAuditSnapshot,
} from '../ErrorState';

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

  it('formats audit snapshot and JSON and supports copy controls (Phase P102)', () => {
    expect(
      formatErrorStateAuditSnapshot({
        title: '网络错误',
        message: '连接超时',
        hasRetry: true,
        retryLabel: '重新连接',
      }),
    ).toBe('errorState|title=网络错误|msg=连接超时|retry=1|retryLabel=重新连接');
    expect(formatErrorStateAuditSnapshot({})).toBe(
      'errorState|title=出错了|msg=none|retry=0|retryLabel=重试',
    );
    expect(
      JSON.parse(
        formatErrorStateAuditJson({
          title: '出错了',
          message: '未知异常',
          hasRetry: false,
          retryLabel: '重试',
        }),
      ),
    ).toEqual({
      title: '出错了',
      message: '未知异常',
      hasRetry: false,
      retryLabel: '重试',
    });

    render(<ErrorState message="msg" />);
    const snapBtn = screen.getByTestId('error-state-copy-snapshot');
    const jsonBtn = screen.getByTestId('error-state-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
