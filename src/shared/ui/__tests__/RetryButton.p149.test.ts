import { describe, expect, it } from 'vitest';

import { auditRetryButtonGovernance } from '../RetryButton/RetryButton';

describe('RetryButton P149 governance audit', () => {
  it('returns healthy defaults for RetryButton governance', () => {
    const res = auditRetryButtonGovernance();
    expect(res.module).toBe('src/shared/ui/RetryButton/RetryButton.tsx');
    expect(res.phase).toBe('P149');
    expect(res.loading).toBe(false);
    expect(res.cooldownRemainingSec).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes loading and clamps cooldownRemainingSec', () => {
    const res = auditRetryButtonGovernance({
      loading: true,
      cooldownRemainingSec: 999,
    });
    expect(res.loading).toBe(true);
    expect(res.cooldownRemainingSec).toBe(300);
    expect(res.healthy).toBe(true);
  });
});
