import { describe, expect, it } from 'vitest';

import { auditDomainEntityTypesGovernance } from '../types/domainEntityTypes';

describe('domainEntityTypes P146 governance audit', () => {
  it('returns healthy defaults for domainEntityTypes governance', () => {
    const res = auditDomainEntityTypesGovernance();
    expect(res.module).toBe('src/shared/api/types/domainEntityTypes.ts');
    expect(res.phase).toBe('P146');
    expect(res.heartbeatStatus).toBe('healthy');
    expect(res.teamStatus).toBe('running');
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when heartbeatStatus is stalled', () => {
    const res = auditDomainEntityTypesGovernance({
      heartbeatStatus: 'stalled',
      teamStatus: 'completed',
    });
    expect(res.heartbeatStatus).toBe('stalled');
    expect(res.teamStatus).toBe('completed');
    expect(res.healthy).toBe(false);
  });
});
