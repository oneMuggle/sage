import { describe, expect, it } from 'vitest';

import { auditWorkspaceIndexGovernance } from '../index';

describe('auditWorkspaceIndexGovernance (P170)', () => {
  it('returns compliant governance audit metadata for workspace barrel', () => {
    const report = auditWorkspaceIndexGovernance();
    expect(report.module).toBe('src/features/workspace/index.ts');
    expect(report.phase).toBe('P170');
    expect(report.domain).toBe('workspace');
    expect(report.exportedComponents).toEqual(['WorkspaceBindModal', 'WorkspaceEmptyGuard']);
    expect(report.compliant).toBe(true);
  });
});
