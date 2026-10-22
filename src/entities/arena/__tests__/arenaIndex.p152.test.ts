import { describe, expect, it } from 'vitest';

import { auditArenaEntityBarrelGovernance } from '../index';

describe('arena entity barrel P152 governance audit', () => {
  it('returns healthy defaults for arena entity barrel governance', () => {
    const res = auditArenaEntityBarrelGovernance();
    expect(res.module).toBe('src/entities/arena/index.ts');
    expect(res.phase).toBe('P152');
    expect(res.exportedHelperCount).toBe(20);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when exportedHelperCount is below 5', () => {
    const res = auditArenaEntityBarrelGovernance({ exportedHelperCount: 2 });
    expect(res.exportedHelperCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
