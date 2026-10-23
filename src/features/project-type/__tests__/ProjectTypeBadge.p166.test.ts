import { describe, expect, it } from 'vitest';

import { auditProjectTypeBadgeGovernance } from '../ProjectTypeBadge';

describe('auditProjectTypeBadgeGovernance (P166)', () => {
  it('returns compliant governance audit metadata for ProjectTypeBadge', () => {
    const report = auditProjectTypeBadgeGovernance();
    expect(report.module).toBe('src/features/project-type/ProjectTypeBadge.tsx');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('project-type');
    expect(report.supportsDetectedIndicator).toBe(true);
    expect(report.supportsSnapshotCopy).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
