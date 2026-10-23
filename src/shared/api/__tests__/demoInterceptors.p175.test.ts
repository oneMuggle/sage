import { describe, expect, it } from 'vitest';

import { auditDemoInterceptorsGovernance } from '../demoInterceptors';

describe('auditDemoInterceptorsGovernance (P175)', () => {
  it('returns compliant governance audit metadata for demoInterceptors', () => {
    const report = auditDemoInterceptorsGovernance();
    expect(report.module).toBe('src/shared/api/demoInterceptors.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.registeredHandlerCount).toBeGreaterThan(0);
    expect(report.compliant).toBe(true);
  });
});
