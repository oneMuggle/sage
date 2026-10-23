import { describe, expect, it } from 'vitest';

import { auditPlanApprovalBarGovernance } from '../PlanApprovalBar';

describe('PlanApprovalBar P142 governance audit', () => {
  it('returns healthy defaults for PlanApprovalBar governance', () => {
    const res = auditPlanApprovalBarGovernance();
    expect(res.module).toBe('src/pages/chat/PlanApprovalBar.tsx');
    expect(res.phase).toBe('P142');
    expect(res.stepCount).toBe(3);
    expect(res.approvalState).toBe('pending');
    expect(res.canEditPlan).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes stepCount and approvalState', () => {
    const res = auditPlanApprovalBarGovernance({
      stepCount: 6.4,
      approvalState: 'approved',
      canEditPlan: false,
    });
    expect(res.stepCount).toBe(6);
    expect(res.approvalState).toBe('approved');
    expect(res.canEditPlan).toBe(false);
    expect(res.healthy).toBe(true);
  });
});
