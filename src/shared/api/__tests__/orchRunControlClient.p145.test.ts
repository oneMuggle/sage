import { describe, expect, it } from 'vitest';

import { auditOrchRunControlClientGovernance } from '../orchRunControlClient';

describe('orchRunControlClient P145 governance audit', () => {
  it('returns healthy defaults for orchRunControlClient governance', () => {
    const res = auditOrchRunControlClientGovernance();
    expect(res.module).toBe('src/shared/api/orchRunControlClient.ts');
    expect(res.phase).toBe('P145');
    expect(res.supportsSteer).toBe(true);
    expect(res.supportsCancel).toBe(true);
    expect(res.supportsApprovalMode).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when a control action is disabled', () => {
    const res = auditOrchRunControlClientGovernance({
      supportsSteer: true,
      supportsCancel: false,
      supportsApprovalMode: true,
    });
    expect(res.supportsCancel).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
