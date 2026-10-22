import { describe, expect, it } from 'vitest';

import {
  evaluateGoalProgressAudit,
  exportGoalProgressAuditJson,
} from '../GoalProgress';

describe('GoalProgress audit diagnostics (Phase P134)', () => {
  it('computes completion rate for valid step counts', () => {
    const report = evaluateGoalProgressAudit({
      completedSteps: 4,
      totalSteps: 8,
      failedSteps: 0,
      inProgressSteps: 1,
    });
    expect(report.healthy).toBe(true);
    expect(report.completionRatePct).toBe(50);
  });

  it('flags failed steps and step count overflow', () => {
    const parsed = JSON.parse(
      exportGoalProgressAuditJson({
        completedSteps: 4,
        totalSteps: 5,
        failedSteps: 2,
        inProgressSteps: 1,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('failed_steps_present');
    expect(parsed.issueCodes).toContain('step_count_overflow');
  });
});
