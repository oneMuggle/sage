/**
 * Public surface of the workspace feature (Task 5, 2026-07-26).
 *
 * - `WorkspaceBindModal`: the bind/change/revoke UI used by the Office page.
 *
 * The actual state owner lives in `app/providers/SessionWorkspaceProvider`.
 * Consumers should not reach into the context directly from this module —
 * use `useCurrentWorkspace` or `useWorkspaceContext` instead.
 */
export { WorkspaceBindModal } from './WorkspaceBindModal';
export type { WorkspaceBindModalProps } from './WorkspaceBindModal';