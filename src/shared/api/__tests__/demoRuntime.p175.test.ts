import { describe, expect, it } from 'vitest';

import { auditDemoRuntimeGovernance } from '../demoRuntime';

describe('auditDemoRuntimeGovernance (P175)', () => {
  it('returns compliant governance audit metadata for demoRuntime', () => {
    const report = auditDemoRuntimeGovernance();
    expect(report.module).toBe('src/shared/api/demoRuntime.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.supportsDemoModeOverride).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
