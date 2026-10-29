/**
 * Last workspace path persistence (2026-10-19, P1).
 *
 * Remembers the workspace directory the user last bound, so a newly created
 * session can auto-bind to it instead of starting unbound. Keyed off
 * localStorage only — a stale entry (directory deleted/moved) is detected at
 * bind time by the backend and cleared by the caller.
 *
 * 2026-10-29 (feat/workspace-optimization): localStorage is being superseded
 * by the backend ``preferences`` table. The ``migrateLastWorkspaceToBackend``
 * helper reads the legacy key once, POSTs it to the backend, and clears the
 * localStorage entry on success. The getter/setter/clear functions stay
 * around for the migration and for audit helpers.
 */

import { invoke } from '../api/desktopInvoke';

const LAST_WORKSPACE_KEY = 'sage-last-workspace-path';

export function getLastWorkspacePath(): string | null {
  try {
    return localStorage.getItem(LAST_WORKSPACE_KEY);
  } catch {
    // Private mode / storage disabled
    return null;
  }
}

export function setLastWorkspacePath(workspacePath: string): void {
  try {
    localStorage.setItem(LAST_WORKSPACE_KEY, workspacePath);
  } catch {
    // Quota exceeded / storage disabled — non-fatal
  }
}

export function clearLastWorkspacePath(): void {
  try {
    localStorage.removeItem(LAST_WORKSPACE_KEY);
  } catch {
    // Non-fatal
  }
}

/**
 * One-shot migration: push the legacy localStorage value to the backend
 * ``preferences`` table, then drop the local key on success.
 *
 * Safe to call multiple times:
 *   - no legacy value → returns ``{ outcome: 'empty' }``
 *   - backend already has a preference → returns ``{ outcome: 'already_present' }``
 *     and clears the localStorage key (backend is authoritative)
 *   - path rejected (missing/non-directory) → returns ``{ outcome: 'rejected' }``
 *     and keeps the localStorage key so a transient failure (unmounted drive)
 *     can be retried on a later startup
 *
 * Failure is non-fatal — the caller should swallow errors so a broken
 * migration never blocks app startup.
 */
export async function migrateLastWorkspaceToBackend(): Promise<{
  outcome: 'migrated' | 'already_present' | 'rejected' | 'empty' | 'error';
  path?: string;
  reason?: string;
}> {
  const legacyPath = getLastWorkspacePath();
  if (!legacyPath) {
    return { outcome: 'empty' };
  }
  try {
    const result = await invoke<{
      outcome: 'migrated' | 'already_present' | 'rejected' | 'empty';
      path: string | null;
      reason: string | null;
    }>('workspace_migrate_preference', { path: legacyPath });
    // The backend is authoritative only when it actually took the value.
    // A `rejected` outcome means the path is unusable *right now* (drive not
    // mounted, folder moved back later), so keep the key: deleting it would
    // silently discard the user's remembered choice over a transient state.
    if (result.outcome === 'migrated' || result.outcome === 'already_present') {
      clearLastWorkspacePath();
    }
    return {
      outcome: result.outcome,
      path: result.path ?? undefined,
      reason: result.reason ?? undefined,
    };
  } catch (err: unknown) {
    // Network / IPC failure — leave localStorage intact so a later startup
    // can retry. Surface the error for the caller's logger.
    return {
      outcome: 'error',
      reason: err instanceof Error ? err.message : String(err),
    };
  }
}

export function formatLastWorkspaceSummary(
  workspacePath: string | null = getLastWorkspacePath(),
): string {
  return workspacePath ? `persisted · ${workspacePath}` : 'none';
}

export function formatLastWorkspaceJson(
  workspacePath: string | null = getLastWorkspacePath(),
): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.last_workspace.v1',
      key: LAST_WORKSPACE_KEY,
      persisted: Boolean(workspacePath),
      workspacePath: workspacePath ?? null,
    },
    null,
    2,
  );
}

export function auditLastWorkspaceGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.last_workspace.governance.v1',
      phase: 'P179',
      storageKey: LAST_WORKSPACE_KEY,
      emptySummary: formatLastWorkspaceSummary(null),
      persistedSummary: formatLastWorkspaceSummary('/workspace/sage'),
    },
    null,
    2,
  );
}
