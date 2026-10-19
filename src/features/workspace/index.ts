/**
 * Public surface of the workspace feature.
 *
 * - `WorkspaceBindModal`: the bind/change/revoke UI used by the Office page.
 * - `WorkspaceEmptyGuard`: inline "bind a workspace" prompt (P0, 2026-10-19).
 *
 * The actual state owner lives in `app/providers/SessionWorkspaceProvider`.
 * Consumers should not reach into the context directly from this module —
 * use `useCurrentWorkspace` or `useWorkspaceContext` instead.
 */
export { WorkspaceBindModal } from './WorkspaceBindModal';
export { WorkspaceEmptyGuard } from './WorkspaceEmptyGuard';
export type { WorkspaceGuardFeature } from './WorkspaceEmptyGuard';