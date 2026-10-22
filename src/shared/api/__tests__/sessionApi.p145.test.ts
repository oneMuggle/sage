import { describe, expect, it } from 'vitest';

import { auditSessionApiGovernance } from '../sessionApi';

describe('sessionApi P145 governance audit', () => {
  it('returns healthy defaults for sessionApi governance', () => {
    const res = auditSessionApiGovernance();
    expect(res.module).toBe('src/shared/api/sessionApi.ts');
    expect(res.phase).toBe('P145');
    expect(res.sessionCount).toBe(0);
    expect(res.supportsExport).toBe(true);
    expect(res.supportsSearch).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes sessionCount and export/search flags', () => {
    const res = auditSessionApiGovernance({
      sessionCount: 24.6,
      supportsExport: false,
      supportsSearch: true,
    });
    expect(res.sessionCount).toBe(24);
    expect(res.supportsExport).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
