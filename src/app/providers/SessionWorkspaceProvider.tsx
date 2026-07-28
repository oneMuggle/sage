/**
 * SessionWorkspaceProvider — Task 5 (2026-07-26).
 *
 * Owns the **only** renderer-side state for the active session's workspace
 * binding. Subscribes to `useStore.currentSessionId`; when the session
 * changes, refetches via `workspaceApi.get()` and replaces the binding
 * (the previous session's binding is not relevant anymore).
 *
 * Why a monotonically increasing requestId (instead of an AbortController)?
 * The Electron desktop bridge does not support true abort — the main
 * process has already forwarded the HTTP call. We capture the requestId at
 * the start of every async operation and discard responses whose requestId
 * is older than the latest one. This is functionally equivalent for the
 * renderer: a slow first get() must not clobber a newer session's binding.
 *
 * State updates are immutable: every setState creates a new object so
 * React's referential-equality bailouts work correctly and consumers can
 * diff snapshots safely.
 *
 * `useCurrentWorkspace()` (lives in `shared/lib/workspaceContext`) is a
 * backwards-compatible accessor that returns `binding?.workspacePath ?? undefined`.
 * New consumers should prefer `useWorkspaceContext()` for full lifecycle access.
 */

import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import type { SessionWorkspaceBinding } from '../../shared/api/types';
import { workspaceApi } from '../../shared/api/workspaceApi';
import { useStore } from '../../shared/lib/store';
import { WorkspaceContext } from '../../shared/lib/workspaceContext';

export type WorkspaceStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface WorkspaceContextValue {
  /** The session this state belongs to. Mirrors `useStore.currentSessionId`. */
  sessionId: string | null;
  /** The active binding, or `null` when the session has no workspace yet. */
  binding: SessionWorkspaceBinding | null;
  /** Lifecycle marker for the latest async request. */
  status: WorkspaceStatus;
  /** Last error message, cleared on the next successful operation. */
  error: string | null;
  /** Bind the current session to `workspacePath`. */
  bind: (workspacePath: string) => Promise<void>;
  /** Revoke the current session's binding. */
  revoke: () => Promise<void>;
  /** Re-fetch the binding from the backend. */
  refresh: () => Promise<void>;
}

interface SessionWorkspaceProviderProps {
  children: ReactNode;
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

/**
 * Provider that owns session-bound workspace state. Place once near the
 * top of the tree (above any consumer of `useWorkspaceContext` /
 * `useCurrentWorkspace`).
 */
export function SessionWorkspaceProvider({ children }: SessionWorkspaceProviderProps) {
  const sessionId = useStore((state) => state.currentSessionId);

  const [binding, setBinding] = useState<SessionWorkspaceBinding | null>(null);
  const [status, setStatus] = useState<WorkspaceStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  // requestId monotonically increases per provider instance. Every async
  // operation captures the value at start; only the most-recent
  // capture is allowed to mutate state.
  const requestIdRef = useRef(0);

  // Replace state with a fresh immutable snapshot. Caller is responsible
  // for ensuring `myRequestId === requestIdRef.current`.
  const applyReady = useCallback((myRequestId: number, next: SessionWorkspaceBinding | null) => {
    if (myRequestId !== requestIdRef.current) return;
    setBinding(next);
    setError(null);
    setStatus('ready');
  }, []);

  const applyError = useCallback((myRequestId: number, message: string) => {
    if (myRequestId !== requestIdRef.current) return;
    setError(message);
    setStatus('error');
  }, []);

  // Whenever the active session changes, kick off a fresh get() and
  // leave the previous request's response to be discarded when it
  // eventually resolves.
  useEffect(() => {
    if (!sessionId) {
      requestIdRef.current += 1;
      setBinding(null);
      setStatus('idle');
      setError(null);
      return;
    }
    const myRequestId = ++requestIdRef.current;
    setStatus('loading');
    setError(null);
    void workspaceApi
      .get(sessionId)
      .then((res) => {
        applyReady(myRequestId, res.binding);
      })
      .catch((err: unknown) => {
        applyError(myRequestId, errorMessage(err));
      });
  }, [sessionId, applyReady, applyError]);

  const refresh = useCallback(async (): Promise<void> => {
    if (!sessionId) return;
    const myRequestId = ++requestIdRef.current;
    setStatus('loading');
    setError(null);
    try {
      const res = await workspaceApi.get(sessionId);
      applyReady(myRequestId, res.binding);
    } catch (err: unknown) {
      applyError(myRequestId, errorMessage(err));
      throw err;
    }
  }, [sessionId, applyReady, applyError]);

  const bind = useCallback(
    async (workspacePath: string): Promise<void> => {
      if (!sessionId) {
        throw new Error('No active session; cannot bind workspace.');
      }
      const myRequestId = ++requestIdRef.current;
      setStatus('loading');
      setError(null);
      try {
        const res = await workspaceApi.bind(sessionId, workspacePath);
        applyReady(myRequestId, res.binding);
      } catch (err: unknown) {
        applyError(myRequestId, errorMessage(err));
        throw err;
      }
    },
    [sessionId, applyReady, applyError],
  );

  const revoke = useCallback(async (): Promise<void> => {
    if (!sessionId) return;
    const myRequestId = ++requestIdRef.current;
    setStatus('loading');
    setError(null);
    try {
      await workspaceApi.revoke(sessionId);
      applyReady(myRequestId, null);
    } catch (err: unknown) {
      applyError(myRequestId, errorMessage(err));
      throw err;
    }
  }, [sessionId, applyReady, applyError]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({ sessionId, binding, status, error, bind, revoke, refresh }),
    [sessionId, binding, status, error, bind, revoke, refresh],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWorkspaceContext(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error(
      'useWorkspaceContext must be used inside <SessionWorkspaceProvider>. ' +
        'Mount the provider in AppProviders (or your app shell) before using this hook.',
    );
  }
  return ctx;
}