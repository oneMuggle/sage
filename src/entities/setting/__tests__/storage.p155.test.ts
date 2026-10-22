import { describe, expect, it } from 'vitest';

import { auditSettingStorageGovernance } from '../storage';

describe('setting storage P155 governance audit', () => {
  it('returns healthy defaults for setting storage governance', () => {
    const res = auditSettingStorageGovernance();
    expect(res.module).toBe('src/entities/setting/storage.ts');
    expect(res.phase).toBe('P155');
    expect(res.endpointCount).toBe(1);
    expect(res.sanitized).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when endpointCount is 0 or sanitized is false', () => {
    const res = auditSettingStorageGovernance({
      endpointCount: 0,
      sanitized: false,
    });
    expect(res.endpointCount).toBe(0);
    expect(res.sanitized).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
