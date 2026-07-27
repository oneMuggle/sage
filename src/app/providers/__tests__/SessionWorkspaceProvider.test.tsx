/**
 * SessionWorkspaceProvider — Task 5 RED tests (2026-07-26).
 *
 * Coverage:
 *   - useWorkspaceContext throws a clear error when no provider is mounted.
 *   - Idle / loading / binding-present / null-binding / error lifecycle
 *     (status transitions driven by sessionId subscription + workspaceApi calls).
 *   - bind / revoke / refresh round-trip and the corresponding status flips.
 *   - Session change: a new sessionId triggers a fresh get() and the stale
 *     response from the previous session does NOT clobber the new state.
 *   - useCurrentWorkspace() is a backwards-compatible accessor that returns
 *     `binding?.workspacePath` (or undefined when no provider / no binding).
 *   - bind() rejects with the API error and the context lands in 'error' state.
 *   - refresh() resets an error state back to 'ready' on success.
 *
 * Implementation note: the provider uses a monotonically increasing
 * requestId (rather than AbortController, since the desktop IPC bridge does
 * not support true abort). Each pending operation captures the requestId at
 * start; only the latest response is allowed to update state.
 */

import { act, render, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockBind = vi.fn();
const mockGet = vi.fn();
const mockRevoke = vi.fn();

vi.mock('../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    bind: (...args: unknown[]) => mockBind(...args),
    get: (...args: unknown[]) => mockGet(...args),
    revoke: (...args: unknown[]) => mockRevoke(...args),
  },
}));

import {
  SessionWorkspaceProvider,
  useWorkspaceContext,
  type WorkspaceContextValue,
} from '../../../app/providers/SessionWorkspaceProvider';
import type {
  SessionWorkspaceBinding,
  WorkspaceRevokeResponse,
} from '../../../shared/api/types';
import { useStore } from '../../../shared/lib/store';
import { useCurrentWorkspace } from '../../../shared/lib/workspaceContext';

const BINDING_A: SessionWorkspaceBinding = {
  sessionId: 'session-a',
  workspacePath: '/tmp/ws-a',
  generation: 1,
  activatedAt: 100,
  revokedAt: null,
};

const BINDING_B: SessionWorkspaceBinding = {
  sessionId: 'session-b',
  workspacePath: '/tmp/ws-b',
  generation: 1,
  activatedAt: 200,
  revokedAt: null,
};

beforeEach(() => {
  mockBind.mockReset();
  mockGet.mockReset();
  mockRevoke.mockReset();
  mockGet.mockResolvedValue({ binding: null });
  useStore.setState({ currentSessionId: null, sessions: [], messages: [] });
});

afterEach(() => {
  useStore.setState({ currentSessionId: null });
});

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
}
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeWrapper(initialSessionId: string | null) {
  useStore.setState({ currentSessionId: initialSessionId });
  return ({ children }: { children: ReactNode }) => (
    <SessionWorkspaceProvider>{children}</SessionWorkspaceProvider>
  );
}

describe('SessionWorkspaceProvider — provider boundary', () => {
  it('useWorkspaceContext throws a descriptive error when no provider is mounted', () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      expect(() => renderHook(() => useWorkspaceContext())).toThrow(
        /useWorkspaceContext must be used inside/,
      );
    } finally {
      errSpy.mockRestore();
    }
  });

  it('useCurrentWorkspace returns undefined when no provider is mounted', () => {
    const { result } = renderHook(() => useCurrentWorkspace());
    expect(result.current).toBeUndefined();
  });
});

describe('SessionWorkspaceProvider — initial lifecycle', () => {
  it('starts in idle when there is no currentSessionId', async () => {
    mockGet.mockResolvedValue({ binding: null });
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper(null),
    });
    expect(mockGet).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(result.current.status).toBe('idle');
    });
    expect(result.current.binding).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.sessionId).toBeNull();
  });

  it('moves to loading then ready when a session with no binding is set', async () => {
    mockGet.mockResolvedValue({ binding: null });
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('session-a'));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.binding).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('moves to ready with the binding when get returns one', async () => {
    mockGet.mockResolvedValue({ binding: BINDING_A });
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.binding).toEqual(BINDING_A);
  });

  it('lands in error state when get rejects', async () => {
    mockGet.mockRejectedValue(new Error('backend boom'));
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toMatch(/backend boom/);
    expect(result.current.binding).toBeNull();
  });

  it('refresh() resets an error state back to ready on success', async () => {
    mockGet.mockRejectedValueOnce(new Error('first call fails'));
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current.status).toBe('error'));
    mockGet.mockResolvedValueOnce({ binding: BINDING_A });
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.status).toBe('ready');
    expect(result.current.error).toBeNull();
    expect(result.current.binding).toEqual(BINDING_A);
  });
});

describe('SessionWorkspaceProvider — bind()', () => {
  it('calls workspaceApi.bind with the current sessionId and path', async () => {
    mockGet.mockResolvedValue({ binding: null });
    mockBind.mockResolvedValue({ binding: BINDING_A });
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    await act(async () => {
      await result.current.bind('/tmp/ws-a');
    });
    expect(mockBind).toHaveBeenCalledWith('session-a', '/tmp/ws-a');
    expect(result.current.binding).toEqual(BINDING_A);
  });

  it('bind() lands in error state when the API rejects', async () => {
    mockGet.mockResolvedValue({ binding: null });
    mockBind.mockRejectedValue(new Error('bind refused'));
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    await act(async () => {
      await expect(result.current.bind('/tmp/ws-a')).rejects.toThrow(/bind refused/);
    });
    expect(result.current.status).toBe('error');
    expect(result.current.error).toMatch(/bind refused/);
    expect(result.current.binding).toBeNull();
  });
});

describe('SessionWorkspaceProvider — revoke()', () => {
  it('calls workspaceApi.revoke and clears the binding', async () => {
    mockGet.mockResolvedValue({ binding: BINDING_A });
    mockRevoke.mockResolvedValue({ revoked: true, generation: 2 } satisfies WorkspaceRevokeResponse);
    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current.binding).toEqual(BINDING_A));
    await act(async () => {
      await result.current.revoke();
    });
    expect(mockRevoke).toHaveBeenCalledWith('session-a');
    expect(result.current.binding).toBeNull();
    expect(result.current.status).toBe('ready');
  });
});

describe('SessionWorkspaceProvider — session change', () => {
  it('re-fetches when currentSessionId changes (b → a), and the stale response does not clobber state', async () => {
    const firstForB = deferred<{ binding: SessionWorkspaceBinding | null }>();
    const secondForA = deferred<{ binding: SessionWorkspaceBinding | null }>();
    mockGet.mockImplementation((sessionId: string) => {
      if (sessionId === 'session-b') return firstForB.promise;
      if (sessionId === 'session-a') return secondForA.promise;
      return Promise.resolve({ binding: null });
    });

    const { result } = renderHook(() => useWorkspaceContext(), {
      wrapper: makeWrapper('session-b'),
    });

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('session-b'));

    act(() => {
      useStore.setState({ currentSessionId: 'session-a' });
    });

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('session-a'));

    await act(async () => {
      secondForA.resolve({ binding: BINDING_A });
    });
    await waitFor(() => expect(result.current.binding).toEqual(BINDING_A));
    expect(result.current.sessionId).toBe('session-a');

    await act(async () => {
      firstForB.resolve({ binding: BINDING_B });
    });
    await waitFor(() => expect(result.current.binding).toEqual(BINDING_A));
    expect(result.current.sessionId).toBe('session-a');
  });
});

describe('SessionWorkspaceProvider — useCurrentWorkspace', () => {
  it('returns binding.workspacePath inside a provider', async () => {
    mockGet.mockResolvedValue({ binding: BINDING_A });
    const { result } = renderHook(() => useCurrentWorkspace(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current).toBe('/tmp/ws-a'));
  });

  it('returns undefined when the binding is null (session has no workspace yet)', async () => {
    mockGet.mockResolvedValue({ binding: null });
    const { result } = renderHook(() => useCurrentWorkspace(), {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => expect(result.current).toBeUndefined());
  });
});

describe('SessionWorkspaceProvider — state immutability', () => {
  it('every state update produces a new context object', async () => {
    mockGet.mockResolvedValue({ binding: null });
    const snapshots: WorkspaceContextValue[] = [];
    const RefCapture = () => {
      const ctx = useWorkspaceContext();
      snapshots.push(ctx);
      return null;
    };
    render(<RefCapture />, {
      wrapper: makeWrapper('session-a'),
    });
    await waitFor(() => {
      const last = snapshots[snapshots.length - 1];
      expect(last.status).toBe('ready');
    });
    const uniqueRefs = new Set(snapshots);
    expect(uniqueRefs.size).toBeGreaterThanOrEqual(2);
  });
});