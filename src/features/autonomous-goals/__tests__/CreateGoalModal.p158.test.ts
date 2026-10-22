import { describe, expect, it } from 'vitest';

import { auditCreateGoalModalGovernance } from '../CreateGoalModal';

describe('CreateGoalModal P158 governance audit', () => {
  it('returns healthy defaults for CreateGoalModal governance', () => {
    const res = auditCreateGoalModalGovernance();
    expect(res.module).toBe('src/features/autonomous-goals/CreateGoalModal.tsx');
    expect(res.phase).toBe('P158');
    expect(res.isOpen).toBe(false);
    expect(res.maxTurns).toBe(10);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when maxTurns is 0 or exceeds 100', () => {
    const res = auditCreateGoalModalGovernance({
      isOpen: true,
      maxTurns: 0,
    });
    expect(res.isOpen).toBe(true);
    expect(res.maxTurns).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
