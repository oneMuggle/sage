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
import { migrateLastWorkspaceToBackend } from '../../shared/lib/lastWorkspace';
import { useStore } from '../../shared/lib/store';
import { WorkspaceContext } from '../../shared/lib/workspaceContext';
import { clientLogger } from '../../shared/log/client';

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

export interface SessionWorkspaceAuditInput {
  sessionId: string | null;
  hasBinding: boolean;
  status: WorkspaceStatus;
  hasError: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSessionWorkspaceAuditSnapshot(input: SessionWorkspaceAuditInput): string {
  return `session=${input.sessionId ?? 'none'}|bound=${input.hasBinding ? 1 : 0}|status=${input.status}|err=${input.hasError ? 1 : 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSessionWorkspaceAuditJson(input: SessionWorkspaceAuditInput): string {
  return JSON.stringify({
    sessionId: input.sessionId,
    hasBinding: input.hasBinding,
    status: input.status,
    hasError: input.hasError,
  });
}

interface SessionWorkspaceProviderProps {
  children: ReactNode;
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

// Preference writes are fire-and-forget, but their *order* matters: a revoke
// fired right after a bind must not land before the bind's setPreference,
// otherwise the remembered path survives the revoke. Chaining every write on
// one promise serialises them in call order.
let preferenceWriteChain: Promise<unknown> = Promise.resolve();

function queuePreferenceWrite(op: () => Promise<unknown>, context: string): void {
  preferenceWriteChain = preferenceWriteChain.then(op).catch((err: unknown) => {
    clientLogger.warn(`${context}: preference write failed`, {
      error: err instanceof Error ? err.message : String(err),
    });
  });
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
  // P17: 追踪最近一次登记到 sage-file 注册表的工作区路径，
  // 绑定变更时注销旧根（最小权限原则）。
  const lastRegisteredRoot = useRef<string | null>(null);
  // 2026-10-29 (feat/workspace-optimization): legacy localStorage → 后端
  // preferences 的一次性迁移守卫。StrictMode 下 effect 会双跑，用 ref 拦住。
  const migrationStartedRef = useRef(false);

  // 2026-10-29 (feat/workspace-optimization): 启动时把 legacy localStorage 里
  // 记住的工作区路径迁入后端 ``preferences`` 表。后端是决策链的单一来源，
  // 前端不再自行推导。迁移失败不阻塞渲染——下次启动会重试。
  useEffect(() => {
    if (migrationStartedRef.current) return;
    migrationStartedRef.current = true;
    void migrateLastWorkspaceToBackend().then((result) => {
      if (result.outcome === 'empty') return;
      clientLogger.info('SessionWorkspaceProvider: workspace preference migration', {
        outcome: result.outcome,
        path: result.path,
        reason: result.reason,
      });
    });
  }, []);

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
        // P13: 绑定的工作区同步登记到主进程 sage-file 注册表，
        // 使 MarkdownImage 的 sage-file:// URL 可被校验放行。
        // P17: 同时注销旧工作区根，防止旧路径永久残留在白名单中。
        const api = window.electronAPI?.sageFile;
        const ws = res.binding?.workspacePath;
        if (api) {
          if (lastRegisteredRoot.current && lastRegisteredRoot.current !== ws) {
            void api.unregisterRoot(lastRegisteredRoot.current).catch(() => undefined);
          }
          if (ws) {
            lastRegisteredRoot.current = ws;
            void api.registerRoot(ws).catch(() => undefined);
          } else {
            lastRegisteredRoot.current = null;
          }
        }
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
        // 2026-10-29 (feat/workspace-optimization): 把显式选择的工作区同步写入
        // ``preferences``（最高优先级输入）。失败不阻塞 bind 主流程——会话绑定
        // 成功比"记住偏好"更重要，下次启动时用户重新选择即可。
        queuePreferenceWrite(() => workspaceApi.setPreference(workspacePath), 'SessionWorkspaceProvider.bind');
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
      // 2026-10-29 (feat/workspace-optimization): 用户显式撤销 → 同时清 preferences。
      // 失败不阻塞 revoke 主流程——会话解绑成功比"清理偏好"更重要。
      queuePreferenceWrite(
        () => workspaceApi.forgetPreference(),
        'SessionWorkspaceProvider.revoke',
      );
    } catch (err: unknown) {
      applyError(myRequestId, errorMessage(err));
      throw err;
    }
  }, [sessionId, applyReady, applyError]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({ sessionId, binding, status, error, bind, revoke, refresh }),
    [sessionId, binding, status, error, bind, revoke, refresh],
  );

  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const auditInput: SessionWorkspaceAuditInput = {
    sessionId,
    hasBinding: Boolean(binding?.workspacePath),
    status,
    hasError: Boolean(error),
  };
  const auditSnapshot = formatSessionWorkspaceAuditSnapshot(auditInput);
  const auditJson = formatSessionWorkspaceAuditJson(auditInput);
  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(auditSnapshot);
    } catch {
      // ignore clipboard errors
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(auditJson);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
      <span
        data-testid="session-workspace-audit-status"
        data-session-workspace-audit={auditSnapshot}
        className="sr-only"
      >
        <span
          role="status"
          tabIndex={0}
          data-testid="session-workspace-audit-copy"
          data-session-workspace-audit={auditSnapshot}
          aria-label="复制会话工作区审计快照"
          onClick={() => void handleCopySnapshot()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              void handleCopySnapshot();
            }
          }}
        >
          {copiedSnapshot ? '已复制' : '快照'}
        </span>
        <span
          role="status"
          tabIndex={0}
          data-testid="session-workspace-audit-copy-json"
          data-session-workspace-audit-json={auditJson}
          aria-label="复制会话工作区审计 JSON"
          onClick={() => void handleCopyJson()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              void handleCopyJson();
            }
          }}
        >
          {copiedJson ? '已复制 JSON' : 'JSON'}
        </span>
      </span>
    </WorkspaceContext.Provider>
  );
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

// eslint-disable-next-line react-refresh/only-export-components
export function auditSessionWorkspaceProviderGovernance(
  state: {
    status?: WorkspaceStatus | string;
    hasActiveSession?: boolean;
  } = {},
): {
  module: 'src/app/providers/SessionWorkspaceProvider.tsx';
  phase: 'P151';
  status: WorkspaceStatus;
  hasActiveSession: boolean;
  healthy: boolean;
} {
  const status: WorkspaceStatus =
    state.status === 'idle' ||
    state.status === 'loading' ||
    state.status === 'error'
      ? state.status
      : 'ready';
  const hasActiveSession = state.hasActiveSession !== false;
  return {
    module: 'src/app/providers/SessionWorkspaceProvider.tsx',
    phase: 'P151',
    status,
    hasActiveSession,
    healthy: status !== 'error',
  };
}
