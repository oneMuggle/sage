/**
 * Last workspace path persistence (2026-10-19, P1).
 *
 * Remembers the workspace directory the user last bound, so a newly created
 * session can auto-bind to it instead of starting unbound. Keyed off
 * localStorage only — a stale entry (directory deleted/moved) is detected at
 * bind time by the backend and cleared by the caller.
 */

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
