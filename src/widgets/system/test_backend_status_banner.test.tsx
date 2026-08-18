import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BackendStatusBanner } from './BackendStatusBanner';

// Test-only payload type — kept loose (no any) so we exercise the component's
// own narrowing. See `BackendStatusBanner.tsx` payload handlers for the
// concrete shape; for the seam, `unknown` + assertion in the cb is enough.
type BackendEventPayload = unknown;

const mockListeners = new Map<string, (payload: BackendEventPayload) => void>();

beforeEach(() => {
  mockListeners.clear();
  (window as unknown as Record<string, unknown>).electronAPI = {
    listen: vi.fn((event: string, cb: (payload: BackendEventPayload) => void) => {
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