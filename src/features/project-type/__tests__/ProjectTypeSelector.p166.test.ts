import { describe, expect, it } from 'vitest';

import { auditProjectTypeSelectorGovernance } from '../ProjectTypeSelector';

describe('auditProjectTypeSelectorGovernance (P166)', () => {
  it('returns compliant governance audit metadata for ProjectTypeSelector', () => {
    const report = auditProjectTypeSelectorGovernance();
    expect(report.module).toBe('src/features/project-type/ProjectTypeSelector.tsx');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('project-type');
    expect(report.supportsAutoDetection).toBe(true);
    expect(report.supportsBlueprintSuiteExport).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
