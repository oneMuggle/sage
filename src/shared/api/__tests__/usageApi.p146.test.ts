import { describe, expect, it } from 'vitest';

import { auditUsageApiGovernance } from '../usageApi';

describe('usageApi P146 governance audit', () => {
  it('returns healthy defaults for usageApi governance', () => {
    const res = auditUsageApiGovernance();
    expect(res.module).toBe('src/shared/api/usageApi.ts');
    expect(res.phase).toBe('P146');
    expect(res.activeRange).toBe('7d');
    expect(res.supportsCsvExport).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes activeRange and supportsCsvExport', () => {
    const res = auditUsageApiGovernance({
      activeRange: '30d',
      supportsCsvExport: false,
    });
    expect(res.activeRange).toBe('30d');
    expect(res.supportsCsvExport).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
