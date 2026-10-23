import { describe, expect, it } from 'vitest';

import { auditThemeCssTypesGovernance } from '../themeCssTypes';

describe('auditThemeCssTypesGovernance (P169)', () => {
  it('returns compliant governance audit metadata for themeCssTypes', () => {
    const report = auditThemeCssTypesGovernance();
    expect(report.module).toBe('src/features/theme/themeCssTypes.ts');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('theme');
    expect(report.maxCssChars).toBe(8192);
    expect(report.maxNameChars).toBe(32);
    expect(report.compliant).toBe(true);
  });
});
