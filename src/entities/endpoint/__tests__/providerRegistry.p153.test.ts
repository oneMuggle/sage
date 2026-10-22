import { describe, expect, it } from 'vitest';

import { auditProviderRegistryGovernance, listProviders } from '../providerRegistry';

describe('providerRegistry P153 governance audit', () => {
  it('returns healthy defaults for providerRegistry governance', () => {
    const res = auditProviderRegistryGovernance();
    expect(res.module).toBe('src/entities/endpoint/providerRegistry.ts');
    expect(res.phase).toBe('P153');
    expect(res.providerCount).toBe(listProviders().length);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when providerCount is 0', () => {
    const res = auditProviderRegistryGovernance({ providerCount: 0 });
    expect(res.providerCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
