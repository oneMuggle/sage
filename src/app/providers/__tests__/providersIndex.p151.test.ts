import { describe, expect, it } from 'vitest';

import { auditProvidersBarrelGovernance } from '../index';

describe('providers barrel P151 governance audit', () => {
  it('returns healthy defaults for providers barrel governance', () => {
    const res = auditProvidersBarrelGovernance();
    expect(res.module).toBe('src/app/providers/index.ts');
    expect(res.phase).toBe('P151');
    expect(res.exportedCount).toBe(6);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when exportedCount is below 5', () => {
    const res = auditProvidersBarrelGovernance({ exportedCount: 2 });
    expect(res.exportedCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
