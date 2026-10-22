import { describe, expect, it } from 'vitest';

import { auditAppProvidersGovernance } from '../AppProviders';

describe('AppProviders P151 governance audit', () => {
  it('returns healthy defaults for AppProviders governance', () => {
    const res = auditAppProvidersGovernance();
    expect(res.module).toBe('src/app/providers/AppProviders.tsx');
    expect(res.phase).toBe('P151');
    expect(res.providerLayerCount).toBe(5);
    expect(res.hasChildren).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when providerLayerCount is low or hasChildren is false', () => {
    const res = auditAppProvidersGovernance({
      providerLayerCount: 1,
      hasChildren: false,
    });
    expect(res.providerLayerCount).toBe(1);
    expect(res.hasChildren).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
