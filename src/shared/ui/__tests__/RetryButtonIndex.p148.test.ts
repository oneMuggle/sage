import { describe, expect, it } from 'vitest';

import { auditRetryButtonBarrelGovernance } from '../RetryButton/index';

describe('RetryButton barrel P148 governance audit', () => {
  it('returns healthy defaults for RetryButton barrel governance', () => {
    const res = auditRetryButtonBarrelGovernance();
    expect(res.module).toBe('src/shared/ui/RetryButton/index.ts');
    expect(res.phase).toBe('P148');
    expect(res.cooldownSeconds).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('clamps cooldownSeconds between 0 and 300', () => {
    expect(auditRetryButtonBarrelGovernance({ cooldownSeconds: 500 }).cooldownSeconds).toBe(300);
    expect(auditRetryButtonBarrelGovernance({ cooldownSeconds: -10 }).cooldownSeconds).toBe(0);
  });
});
