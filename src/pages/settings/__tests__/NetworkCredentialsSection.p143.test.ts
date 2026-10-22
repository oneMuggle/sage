import { describe, expect, it } from 'vitest';

import { auditNetworkCredentialsSectionGovernance } from '../NetworkCredentialsSection';

describe('NetworkCredentialsSection P143 governance audit', () => {
  it('returns healthy defaults for NetworkCredentialsSection governance', () => {
    const res = auditNetworkCredentialsSectionGovernance();
    expect(res.module).toBe('src/pages/settings/NetworkCredentialsSection.tsx');
    expect(res.phase).toBe('P143');
    expect(res.configuredKeyCount).toBe(0);
    expect(res.proxyMode).toBe('system');
    expect(res.tlsVerifyEnabled).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes configuredKeyCount and proxyMode', () => {
    const res = auditNetworkCredentialsSectionGovernance({
      configuredKeyCount: 4.5,
      proxyMode: 'custom',
      tlsVerifyEnabled: false,
    });
    expect(res.configuredKeyCount).toBe(4);
    expect(res.proxyMode).toBe('custom');
    expect(res.tlsVerifyEnabled).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
