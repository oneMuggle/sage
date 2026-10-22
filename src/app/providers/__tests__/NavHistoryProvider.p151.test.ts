import { describe, expect, it } from 'vitest';

import { auditNavHistoryProviderGovernance } from '../NavHistoryProvider';

describe('NavHistoryProvider P151 governance audit', () => {
  it('returns healthy defaults for NavHistoryProvider governance', () => {
    const res = auditNavHistoryProviderGovernance();
    expect(res.module).toBe('src/app/providers/NavHistoryProvider.tsx');
    expect(res.phase).toBe('P151');
    expect(res.entryCount).toBe(1);
    expect(res.maxEntries).toBe(50);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when entryCount is 0 or exceeds maxEntries', () => {
    expect(auditNavHistoryProviderGovernance({ entryCount: 0 }).healthy).toBe(false);
    expect(
      auditNavHistoryProviderGovernance({ entryCount: 100, maxEntries: 50 }).healthy,
    ).toBe(false);
  });
});
