import { describe, expect, it } from 'vitest';

import { auditGoalStoreGovernance } from '../goalStore';

describe('goalStore P152 governance audit', () => {
  it('returns healthy defaults for goalStore governance', () => {
    const res = auditGoalStoreGovernance();
    expect(res.module).toBe('src/entities/autonomous-goals/goalStore.ts');
    expect(res.phase).toBe('P152');
    expect(res.goalCount).toBe(0);
    expect(res.hasError).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasError is true', () => {
    const res = auditGoalStoreGovernance({
      goalCount: 3,
      hasError: true,
    });
    expect(res.goalCount).toBe(3);
    expect(res.hasError).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
