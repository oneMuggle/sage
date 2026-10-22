import { describe, expect, it } from 'vitest';

import { auditGoalApiGovernance } from '../goalApi';

describe('goalApi P152 governance audit', () => {
  it('returns healthy defaults for goalApi governance', () => {
    const res = auditGoalApiGovernance();
    expect(res.module).toBe('src/entities/autonomous-goals/goalApi.ts');
    expect(res.phase).toBe('P152');
    expect(res.endpointCount).toBe(10);
    expect(res.supportsCheckpoints).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when endpointCount is low or supportsCheckpoints is false', () => {
    const res = auditGoalApiGovernance({
      endpointCount: 2,
      supportsCheckpoints: false,
    });
    expect(res.endpointCount).toBe(2);
    expect(res.supportsCheckpoints).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
