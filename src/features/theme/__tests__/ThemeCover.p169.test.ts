import { describe, expect, it } from 'vitest';

import { auditThemeCoverGovernance } from '../ThemeCover';

describe('auditThemeCoverGovernance (P169)', () => {
  it('returns compliant governance audit metadata for ThemeCover', () => {
    const report = auditThemeCoverGovernance();
    expect(report.module).toBe('src/features/theme/ThemeCover.tsx');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('theme');
    expect(report.supportsGradientFallbackOnError).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
