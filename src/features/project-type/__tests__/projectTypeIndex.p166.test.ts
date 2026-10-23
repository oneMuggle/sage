import { describe, expect, it } from 'vitest';

import { auditProjectTypeBarrelGovernance } from '../index';

describe('auditProjectTypeBarrelGovernance (P166)', () => {
  it('returns compliant governance audit metadata for project-type index barrel', () => {
    const report = auditProjectTypeBarrelGovernance();
    expect(report.module).toBe('src/features/project-type/index.ts');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('project-type');
    expect(report.reExportsStudioAndGovernancePanels).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
