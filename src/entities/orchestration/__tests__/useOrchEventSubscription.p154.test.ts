import { describe, expect, it } from 'vitest';

import { auditUseOrchEventSubscriptionGovernance } from '../useOrchEventSubscription';

describe('useOrchEventSubscription P154 governance audit', () => {
  it('returns healthy defaults for useOrchEventSubscription governance', () => {
    const res = auditUseOrchEventSubscriptionGovernance();
    expect(res.module).toBe('src/entities/orchestration/useOrchEventSubscription.ts');
    expect(res.phase).toBe('P154');
    expect(res.enabled).toBe(true);
    expect(res.reconnectCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when reconnectCount exceeds 10', () => {
    const res = auditUseOrchEventSubscriptionGovernance({
      enabled: false,
      reconnectCount: 15,
    });
    expect(res.enabled).toBe(false);
    expect(res.reconnectCount).toBe(15);
    expect(res.healthy).toBe(false);
  });
});
