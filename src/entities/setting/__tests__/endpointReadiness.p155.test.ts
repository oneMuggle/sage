import { describe, expect, it } from 'vitest';

import { auditEndpointReadinessGovernance } from '../endpointReadiness';

describe('endpointReadiness P155 governance audit', () => {
  it('returns healthy defaults for endpointReadiness governance', () => {
    const res = auditEndpointReadinessGovernance();
    expect(res.module).toBe('src/entities/setting/endpointReadiness.ts');
    expect(res.phase).toBe('P155');
    expect(res.configuredCount).toBe(1);
    expect(res.enabledCount).toBe(1);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when configuredCount or enabledCount is 0', () => {
    const res = auditEndpointReadinessGovernance({
      configuredCount: 0,
      enabledCount: 0,
    });
    expect(res.configuredCount).toBe(0);
    expect(res.enabledCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
