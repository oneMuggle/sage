import { describe, expect, it } from 'vitest';

import { auditTypeDetectionPreviewGovernance } from '../TypeDetectionPreview';

describe('auditTypeDetectionPreviewGovernance (P166)', () => {
  it('returns compliant governance audit metadata for TypeDetectionPreview', () => {
    const report = auditTypeDetectionPreviewGovernance();
    expect(report.module).toBe('src/features/project-type/TypeDetectionPreview.tsx');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('project-type');
    expect(report.lowConfidenceThresholdPercent).toBe(50);
    expect(report.supportsBlueprintInspection).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
