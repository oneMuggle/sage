import { describe, expect, it } from 'vitest';

import { auditRunControlStoreGovernance } from '../runControlStore';

describe('runControlStore P154 governance audit', () => {
  it('returns healthy defaults for runControlStore governance', () => {
    const res = auditRunControlStoreGovernance();
    expect(res.module).toBe('src/entities/orchestration/runControlStore.ts');
    expect(res.phase).toBe('P154');
    expect(res.activeRunCount).toBe(0);
    expect(res.hasError).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasError is true', () => {
    const res = auditRunControlStoreGovernance({
      activeRunCount: 2,
      hasError: true,
    });
    expect(res.activeRunCount).toBe(2);
    expect(res.hasError).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
