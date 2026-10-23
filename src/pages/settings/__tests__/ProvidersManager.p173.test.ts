import { describe, expect, it } from 'vitest';

import { auditProvidersManagerGovernance } from '../ProvidersManager';

describe('auditProvidersManagerGovernance (P173)', () => {
  it('returns compliant governance audit metadata for ProvidersManager', () => {
    const report = auditProvidersManagerGovernance();
    expect(report.module).toBe('src/pages/settings/ProvidersManager.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('settings');
    expect(report.supportsManifestUrlAndCustomUpdateProviders).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
