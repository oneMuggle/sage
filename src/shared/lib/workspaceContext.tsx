/**
 * Workspace context — shared between Chat.tsx (M1-M2 chat-read) and
 * SessionWorkspaceProvider (Task 5, 2026-07-26).
 *
 * History:
 * - M1-M2: this module owned a tiny `string | undefined` context that
 *   `AppProviders` set to `undefined`. The Office page kept its own
 *   `useState`, which meant workspacePath could not be unified between
 *   the Chat page and the Office page.
 * - Task 5: SessionWorkspaceProvider is now the **only** renderer-side
 *   source of truth. This module is reduced to:
 *     1. The `WorkspaceContext` (typed `WorkspaceContextValue | null`)
 *     2. The `useCurrentWorkspace()` accessor — returns
 *        `binding?.workspacePath ?? undefined` so M1-M2 chat-read consumers
 *        (Chat.tsx, AtFileMenu, etc.) keep working without changes.
 *
 * Full lifecycle access (status / error / bind / revoke / refresh) lives
 * on `useWorkspaceContext` (re-exported from SessionWorkspaceProvider).
 */

import { createContext, useContext } from 'react';

import type { WorkspaceContextValue } from '../../app/providers/SessionWorkspaceProvider';

/**
 * Source of truth for the active session's workspace binding. `null` means
 * no provider is mounted; `useCurrentWorkspace` falls back to `undefined`
 * to preserve the M1-M2 chat-read shape.
 */
 
export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

/**
 * Backwards-compatible accessor. Returns the active workspace path string
 * (or `undefined` when no provider is mounted or the session has no
 * workspace bound yet).
 *
 * Use this when you only need the path string — the Chat → ChatInput →
 * AtFileMenu chain uses it. Use `useWorkspaceContext` for full lifecycle
 * access (status / error / bind / revoke / refresh).
 */
 
export function useCurrentWorkspace(): string | undefined {
  const ctx = useContext(WorkspaceContext);
  return ctx?.binding?.workspacePath;
}

// Re-export the value type so consumers do not need to import from
// SessionWorkspaceProvider directly.
export type { WorkspaceContextValue } from '../../app/providers/SessionWorkspaceProvider';