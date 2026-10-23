import { describe, expect, it } from 'vitest';

import { auditNetworkTabGovernance } from '../NetworkTab';

describe('auditNetworkTabGovernance (P172)', () => {
  it('returns compliant governance audit metadata for NetworkTab', () => {
    const report = auditNetworkTabGovernance();
    expect(report.module).toBe('src/pages/settings/NetworkTab.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('settings');
    expect(report.supportsProxySearchAndCredentials).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
