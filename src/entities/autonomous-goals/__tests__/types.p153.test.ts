import { describe, expect, it } from 'vitest';

import { auditAutonomousGoalsTypesGovernance } from '../types';

describe('autonomous-goals types P153 governance audit', () => {
  it('returns healthy defaults for autonomous-goals types governance', () => {
    const res = auditAutonomousGoalsTypesGovernance();
    expect(res.module).toBe('src/entities/autonomous-goals/types.ts');
    expect(res.phase).toBe('P153');
    expect(res.status).toBe('completed');
    expect(res.degradationLevel).toBe('none');
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when status is failed or degradationLevel is stopped', () => {
    const res = auditAutonomousGoalsTypesGovernance({
      status: 'failed',
      degradationLevel: 'stopped',
    });
    expect(res.status).toBe('failed');
    expect(res.degradationLevel).toBe('stopped');
    expect(res.healthy).toBe(false);
  });
});
