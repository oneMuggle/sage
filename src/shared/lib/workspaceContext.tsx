import { createContext, useContext, type ReactNode } from 'react';

/**
 * Current workspace root path, if one is selected by the user.
 *
 * - `undefined` means no workspace is active yet — the AtFileMenu (and any
 *   other consumer) falls back to filesystem-only results.
 * - A non-empty absolute path means a workspace is active; office docs
 *   become visible to consumers like `fileSearchClient.search`.
 *
 * The provider value is intentionally `undefined` by default in M1-M2:
 * Office.tsx still owns its own local `useState` for workspacePath until a
 * follow-up PR migrates it onto this context. Wiring the context here gives
 * Chat.tsx (and future workspace-aware components) a stable integration
 * point without forcing the migration in this PR.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const WorkspaceContext = createContext<string | undefined>(undefined);

interface WorkspaceContextProviderProps {
  value: string | undefined;
  children: ReactNode;
}

/**
 * Tiny provider — keeps the value opt-in at the App level. Renders children
 * unconditionally so callers don't need a sibling provider when no
 * workspace source is wired up yet.
 */
export function WorkspaceContextProvider({ value, children }: WorkspaceContextProviderProps) {
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

/**
 * Read the current workspace path from context. Returns `undefined` when no
 * provider has been mounted or when the provider is set to `undefined`.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useCurrentWorkspace(): string | undefined {
  return useContext(WorkspaceContext);
}
