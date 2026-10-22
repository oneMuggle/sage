import { describe, expect, it } from 'vitest';

import { auditGoalDetailPageGovernance } from '../GoalDetailPage';

describe('GoalDetailPage P158 governance audit', () => {
  it('returns healthy defaults for GoalDetailPage governance', () => {
    const res = auditGoalDetailPageGovernance();
    expect(res.module).toBe('src/features/autonomous-goals/GoalDetailPage.tsx');
    expect(res.phase).toBe('P158');
    expect(res.goalId).toBe('goal-default');
    expect(res.iterationCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when iterationCount exceeds 200', () => {
    const res = auditGoalDetailPageGovernance({
      goalId: 'goal-1',
      iterationCount: 250,
    });
    expect(res.goalId).toBe('goal-1');
    expect(res.iterationCount).toBe(250);
    expect(res.healthy).toBe(false);
  });
});
