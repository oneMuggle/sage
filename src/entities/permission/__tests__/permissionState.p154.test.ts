import { describe, expect, it } from 'vitest';

import { auditPermissionStateGovernance } from '../permissionState';

describe('permissionState P154 governance audit', () => {
  it('returns healthy defaults for permissionState governance', () => {
    const res = auditPermissionStateGovernance();
    expect(res.module).toBe('src/entities/permission/permissionState.ts');
    expect(res.phase).toBe('P154');
    expect(res.pendingCount).toBe(0);
    expect(res.maxQueueDepth).toBe(50);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when pendingCount exceeds maxQueueDepth', () => {
    const res = auditPermissionStateGovernance({
      pendingCount: 60,
      maxQueueDepth: 50,
    });
    expect(res.pendingCount).toBe(60);
    expect(res.maxQueueDepth).toBe(50);
    expect(res.healthy).toBe(false);
  });
});
