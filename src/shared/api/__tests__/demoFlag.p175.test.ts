import { describe, expect, it } from 'vitest';

import { auditDemoFlagGovernance } from '../demoFlag';

describe('auditDemoFlagGovernance (P175)', () => {
  it('returns compliant governance audit metadata for demoFlag', () => {
    const report = auditDemoFlagGovernance();
    expect(report.module).toBe('src/shared/api/demoFlag.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.supportsRuntimeOverrideAndPreloadFlag).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
