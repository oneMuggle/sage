import { describe, expect, it } from 'vitest';

import { auditUpdateFeatureFlagGovernance } from '../updateFeatureFlag';

describe('auditUpdateFeatureFlagGovernance (P174)', () => {
  it('returns compliant governance audit metadata for updateFeatureFlag', () => {
    const report = auditUpdateFeatureFlagGovernance();
    expect(report.module).toBe('src/shared/updateFeatureFlag.ts');
    expect(report.phase).toBe('P174');
    expect(report.domain).toBe('shared');
    expect(report.defaultEnabled).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
