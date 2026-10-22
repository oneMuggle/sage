import { describe, expect, it } from 'vitest';

import {
  evaluateGoalCardAudit,
  exportGoalCardAuditJson,
} from '../GoalCard';

describe('GoalCard audit diagnostics (Phase P134)', () => {
  it('evaluates healthy active goal card', () => {
    const report = evaluateGoalCardAudit({
      goalId: 'goal-1',
      title: 'Ship release',
      status: 'active',
      completedStepCount: 3,
      totalStepCount: 5,
      hasSchedule: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.progressPct).toBe(60);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags failed goal and missing metadata', () => {
    const raw = exportGoalCardAuditJson({
      goalId: ' ',
      title: '',
      status: 'failed',
      completedStepCount: 1,
      totalStepCount: 4,
      hasSchedule: false,
    });
    const parsed = JSON.parse(raw);
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_goal_id');
    expect(parsed.issueCodes).toContain('missing_goal_title');
    expect(parsed.issueCodes).toContain('goal_execution_failed');
  });
});
