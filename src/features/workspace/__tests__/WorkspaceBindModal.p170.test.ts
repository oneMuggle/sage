import { describe, expect, it } from 'vitest';

import { auditWorkspaceBindModalGovernance } from '../WorkspaceBindModal';

describe('auditWorkspaceBindModalGovernance (P170)', () => {
  it('returns compliant governance audit metadata for WorkspaceBindModal', () => {
    const report = auditWorkspaceBindModalGovernance();
    expect(report.module).toBe('src/features/workspace/WorkspaceBindModal.tsx');
    expect(report.phase).toBe('P170');
    expect(report.domain).toBe('workspace');
    expect(report.supportsBindAndRevoke).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
