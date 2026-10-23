import { describe, expect, it } from 'vitest';

import { auditWorkspaceEmptyGuardGovernance } from '../WorkspaceEmptyGuard';

describe('auditWorkspaceEmptyGuardGovernance (P170)', () => {
  it('returns compliant governance audit metadata for WorkspaceEmptyGuard', () => {
    const report = auditWorkspaceEmptyGuardGovernance();
    expect(report.module).toBe('src/features/workspace/WorkspaceEmptyGuard.tsx');
    expect(report.phase).toBe('P170');
    expect(report.domain).toBe('workspace');
    expect(report.supportsInlineFolderPicker).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
