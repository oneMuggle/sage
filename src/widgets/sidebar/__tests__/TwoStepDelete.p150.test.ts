import { describe, expect, it } from 'vitest';

import { auditTwoStepDeleteGovernance } from '../TwoStepDelete';

describe('TwoStepDelete P150 governance audit', () => {
  it('returns healthy defaults for TwoStepDelete governance', () => {
    const res = auditTwoStepDeleteGovernance();
    expect(res.module).toBe('src/widgets/sidebar/TwoStepDelete.tsx');
    expect(res.phase).toBe('P150');
    expect(res.confirmTimeoutMs).toBe(3000);
    expect(res.armed).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('clamps confirmTimeoutMs between 500 and 10000', () => {
    expect(auditTwoStepDeleteGovernance({ confirmTimeoutMs: 100 }).confirmTimeoutMs).toBe(500);
    expect(auditTwoStepDeleteGovernance({ confirmTimeoutMs: 25000 }).confirmTimeoutMs).toBe(10000);
  });
});
