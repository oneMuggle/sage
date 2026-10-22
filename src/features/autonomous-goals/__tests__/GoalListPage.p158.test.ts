import { describe, expect, it } from 'vitest';

import { auditGoalListPageGovernance } from '../GoalListPage';

describe('GoalListPage P158 governance audit', () => {
  it('returns healthy defaults for GoalListPage governance', () => {
    const res = auditGoalListPageGovernance();
    expect(res.module).toBe('src/features/autonomous-goals/GoalListPage.tsx');
    expect(res.phase).toBe('P158');
    expect(res.goalCount).toBe(0);
    expect(res.statusFilter).toBe('all');
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when goalCount exceeds 1000', () => {
    const res = auditGoalListPageGovernance({
      goalCount: 1200,
      statusFilter: 'active',
    });
    expect(res.goalCount).toBe(1200);
    expect(res.statusFilter).toBe('active');
    expect(res.healthy).toBe(false);
  });
});
