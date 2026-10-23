import { describe, expect, it } from 'vitest';

import { auditModelCatalogPageGovernance } from '../ModelCatalog';

describe('auditModelCatalogPageGovernance (P171)', () => {
  it('returns compliant governance audit metadata for ModelCatalog page', () => {
    const report = auditModelCatalogPageGovernance();
    expect(report.module).toBe('src/pages/ModelCatalog.tsx');
    expect(report.phase).toBe('P171');
    expect(report.domain).toBe('pages');
    expect(report.supportsSnapshotReview).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
