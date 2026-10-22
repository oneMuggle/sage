import { describe, expect, it } from 'vitest';

import { auditPermissionApiGovernance } from '../permissionApi';

describe('permissionApi P145 governance audit', () => {
  it('returns healthy defaults for permissionApi governance', () => {
    const res = auditPermissionApiGovernance();
    expect(res.module).toBe('src/shared/api/permissionApi.ts');
    expect(res.phase).toBe('P145');
    expect(res.activePreset).toBe('standard');
    expect(res.presetCount).toBe(3);
    expect(res.autoApprovalCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes activePreset and autoApprovalCount', () => {
    const res = auditPermissionApiGovernance({
      activePreset: 'careful',
      autoApprovalCount: 7.4,
    });
    expect(res.activePreset).toBe('careful');
    expect(res.autoApprovalCount).toBe(7);
    expect(res.healthy).toBe(true);
  });
});
