import { describe, expect, it } from 'vitest';

import { auditBackgroundInjectorGovernance } from '../backgroundInjector';

describe('auditBackgroundInjectorGovernance (P169)', () => {
  it('returns compliant governance audit metadata for backgroundInjector', () => {
    const report = auditBackgroundInjectorGovernance();
    expect(report.module).toBe('src/features/theme/backgroundInjector.ts');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('theme');
    expect(report.supportsPreviewAndPersistedStyles).toBe(true);
    expect(report.escapesDataUrls).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
