import { describe, expect, it } from 'vitest';

import { auditSessionStorageGovernance } from '../storage';

describe('session storage P154 governance audit', () => {
  it('returns healthy defaults for session storage governance', () => {
    const res = auditSessionStorageGovernance();
    expect(res.module).toBe('src/entities/session/storage.ts');
    expect(res.phase).toBe('P154');
    expect(res.hasSessionId).toBe(true);
    expect(res.storageValid).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when storageValid is false', () => {
    const res = auditSessionStorageGovernance({
      hasSessionId: false,
      storageValid: false,
    });
    expect(res.hasSessionId).toBe(false);
    expect(res.storageValid).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
