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

  /**
   * Background (2026-09-02 incident): when SAGE_SKIP_BACKEND=1 and the external
   * backend was started without SAGE_LOCAL_AUTH_TOKEN matching what Electron
   * loaded, /health still answers 200 (public allowlist) but every protected
   * endpoint returns 401. Each page then surfaces its own 401 — memory,
   * orchestration, skills — with no unified banner. The probe in main.ts
   * detects this at startup and emits `backend:auth-failed` so the user gets
   * one clear "重启 Sage" message instead of three independent ones.
   */
  it('shows HTTP-401 specific diagnostic on backend:auth-failed', () => {
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:auth-failed')!({ status: 401 });
    });
    // 401 必须明确显示 — 这是用户能识别"凭据问题 vs 后端崩溃"的关键区分点
    expect(screen.getByText(/401/)).toBeTruthy();
    expect(screen.getByText(/后端授权凭据/)).toBeTruthy();
    // 与 disconnected attempt=-1 的"请重启 Sage"语义对齐，但更精确（强调 HTTP 401）
    expect(screen.getByText(/请重启 Sage/)).toBeTruthy();
  });

  it('does NOT clear auth-failed state on subsequent backend:ready (token 不修复前别假装恢复)', () => {
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:auth-failed')!({ status: 401 });
    });
    expect(screen.getByText(/401/)).toBeTruthy();
    // 主进程 probe 一次性发出 auth-failed 后再发 ready 是无意义的（token 还没修），
    // 但要保证 UI 不会因此消失 — 用户必须重启才能清掉这个状态。
    act(() => {
      mockListeners.get('backend:ready')!({});
    });
    expect(screen.queryByText(/401/)).toBeTruthy();
  });
});
