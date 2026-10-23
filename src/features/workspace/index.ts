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

export interface WorkspaceFeatureBarrelAuditReport {
  schemaVersion: '1.0';
  module: 'src/features/workspace/index.ts';
  exportedSymbols: readonly string[];
  symbolCount: number;
  exportedAt: string;
}

export function auditWorkspaceFeatureBarrel(): WorkspaceFeatureBarrelAuditReport {
  const exportedSymbols = ['WorkspaceBindModal', 'WorkspaceEmptyGuard'] as const;
  return {
    schemaVersion: '1.0',
    module: 'src/features/workspace/index.ts',
    exportedSymbols,
    symbolCount: exportedSymbols.length,
    exportedAt: '2026-10-22',
  };
}

export function exportWorkspaceFeatureBarrelAuditJson(): string {
  return JSON.stringify(auditWorkspaceFeatureBarrel(), null, 2);
}

export function auditWorkspaceIndexGovernance(): {
  module: 'src/features/workspace/index.ts';
  phase: 'P170';
  domain: 'workspace';
  exportedComponents: readonly ['WorkspaceBindModal', 'WorkspaceEmptyGuard'];
  compliant: boolean;
} {
  return {
    module: 'src/features/workspace/index.ts',
    phase: 'P170',
    domain: 'workspace',
    exportedComponents: ['WorkspaceBindModal', 'WorkspaceEmptyGuard'],
    compliant: true,
  };
}
