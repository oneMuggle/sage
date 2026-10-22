import { describe, expect, it } from 'vitest';

import { auditUsageStatsTabGovernance } from '../UsageStatsTab';

describe('UsageStatsTab P143 governance audit', () => {
  it('returns healthy defaults for UsageStatsTab governance', () => {
    const res = auditUsageStatsTabGovernance();
    expect(res.module).toBe('src/pages/settings/UsageStatsTab.tsx');
    expect(res.phase).toBe('P143');
    expect(res.totalTokens).toBe(0);
    expect(res.sessionCount).toBe(0);
    expect(res.timeRangeDays).toBe(30);
    expect(res.healthy).toBe(true);
  });

  it('normalizes token, session, and timeRangeDays values', () => {
    const res = auditUsageStatsTabGovernance({
      totalTokens: 12450.8,
      sessionCount: 15.2,
      timeRangeDays: 7,
    });
    expect(res.totalTokens).toBe(12450);
    expect(res.sessionCount).toBe(15);
    expect(res.timeRangeDays).toBe(7);
    expect(res.healthy).toBe(true);
  });
});
