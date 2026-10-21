import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import {
  LoadingState,
  formatLoadingStateAuditJson,
  formatLoadingStateAuditSnapshot,
} from '../LoadingState';

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

  it('formats audit snapshot and JSON and supports copy controls (Phase P102)', () => {
    expect(
      formatLoadingStateAuditSnapshot({
        variant: 'skeleton',
        label: '正在加载会话',
        rows: 5,
      }),
    ).toBe('loadingState|variant=skeleton|label=正在加载会话|rows=5');
    expect(formatLoadingStateAuditSnapshot({})).toBe(
      'loadingState|variant=spinner|label=加载中…|rows=3',
    );
    expect(
      JSON.parse(
        formatLoadingStateAuditJson({
          variant: 'spinner',
          label: '请稍候',
          rows: 2,
        }),
      ),
    ).toEqual({
      variant: 'spinner',
      label: '请稍候',
      rows: 2,
    });

    render(<LoadingState />);
    const snapBtn = screen.getByTestId('loading-state-copy-snapshot');
    const jsonBtn = screen.getByTestId('loading-state-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
