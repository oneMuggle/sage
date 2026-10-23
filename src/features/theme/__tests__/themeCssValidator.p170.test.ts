import { describe, expect, it } from 'vitest';

import { auditThemeCssValidatorGovernance } from '../themeCssValidator';

describe('auditThemeCssValidatorGovernance (P170)', () => {
  it('returns compliant governance audit metadata for themeCssValidator', () => {
    const report = auditThemeCssValidatorGovernance();
    expect(report.module).toBe('src/features/theme/themeCssValidator.ts');
    expect(report.phase).toBe('P170');
    expect(report.domain).toBe('theme');
    expect(report.enforcesAllowlist).toBe(true);
    expect(report.blocksForbiddenPatterns).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
