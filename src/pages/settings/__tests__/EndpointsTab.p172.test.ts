import { describe, expect, it } from 'vitest';

import { auditEndpointsTabGovernance } from '../EndpointsTab';

describe('auditEndpointsTabGovernance (P172)', () => {
  it('returns compliant governance audit metadata for EndpointsTab', () => {
    const report = auditEndpointsTabGovernance();
    expect(report.module).toBe('src/pages/settings/EndpointsTab.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('settings');
    expect(report.supportsEndpointProbeStatusDisplay).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
