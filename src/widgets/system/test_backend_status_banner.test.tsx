import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';

import { BackendStatusBanner } from './BackendStatusBanner';

const mockListeners = new Map<string, (payload: any) => void>();

beforeEach(() => {
  mockListeners.clear();
  (window as any).electronAPI = {
    listen: vi.fn((event: string, cb: (payload: any) => void) => {
      mockListeners.set(event, cb);
      return () => mockListeners.delete(event);
    }),
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('BackendStatusBanner (PR-B)', () => {
  it('renders nothing when state is ok', () => {
    render(<BackendStatusBanner />);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows reconnecting message on backend:disconnected with attempt=1', () => {
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:disconnected')!({ attempt: 1 });
    });
    expect(screen.getByText(/正在自动重连.*第 1\/3/)).toBeTruthy();
  });

  it('shows restart-required message on backend:disconnected with attempt=-1', () => {
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:disconnected')!({ attempt: -1 });
    });
    expect(screen.getByText(/请重启 Sage/)).toBeTruthy();
  });

  it('shows recovered message on backend:reconnected and clears after 2s', async () => {
    vi.useFakeTimers();
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:disconnected')!({ attempt: 1 });
    });
    act(() => {
      mockListeners.get('backend:reconnected')!({});
    });
    expect(screen.getByText(/已恢复/)).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(screen.queryByText(/已恢复/)).toBeNull();
  });
});