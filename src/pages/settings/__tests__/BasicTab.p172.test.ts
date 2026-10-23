import { describe, expect, it } from 'vitest';

import { auditBasicTabGovernance } from '../BasicTab';

describe('auditBasicTabGovernance (P172)', () => {
  it('returns compliant governance audit metadata for BasicTab', () => {
    const report = auditBasicTabGovernance();
    expect(report.module).toBe('src/pages/settings/BasicTab.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('settings');
    expect(report.supportsTimezoneAndDemoMode).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
