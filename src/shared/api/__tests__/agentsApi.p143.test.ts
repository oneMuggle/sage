import { describe, expect, it } from 'vitest';

import { auditAgentsApiGovernance } from '../agentsApi';

describe('agentsApi P143 governance audit', () => {
  it('returns healthy defaults for agentsApi governance', () => {
    const res = auditAgentsApiGovernance();
    expect(res.module).toBe('src/shared/api/agentsApi.ts');
    expect(res.phase).toBe('P143');
    expect(res.endpointCount).toBe(5);
    expect(res.timeoutMs).toBe(30000);
    expect(res.healthy).toBe(true);
  });

  it('normalizes endpointCount and timeoutMs', () => {
    const res = auditAgentsApiGovernance({
      endpointCount: 8.7,
      timeoutMs: 500,
    });
    expect(res.endpointCount).toBe(8);
    expect(res.timeoutMs).toBe(1000);
    expect(res.healthy).toBe(true);
  });
});
