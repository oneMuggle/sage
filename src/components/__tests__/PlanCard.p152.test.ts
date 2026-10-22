import { describe, expect, it } from 'vitest';

import { auditPlanCardGovernance } from '../PlanCard';

describe('PlanCard P152 governance audit', () => {
  it('returns healthy defaults for PlanCard governance', () => {
    const res = auditPlanCardGovernance();
    expect(res.module).toBe('src/components/PlanCard.tsx');
    expect(res.phase).toBe('P152');
    expect(res.stepCount).toBe(3);
    expect(res.completedCount).toBe(1);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when stepCount is 0', () => {
    const res = auditPlanCardGovernance({
      stepCount: 0,
      completedCount: 5,
    });
    expect(res.stepCount).toBe(0);
    expect(res.completedCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
