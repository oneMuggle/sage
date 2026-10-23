import { describe, expect, it } from 'vitest';

import { auditPagesBarrelGovernance } from '../../index';

describe('pages/index P142 governance audit', () => {
  it('returns healthy defaults for pages barrel governance', () => {
    const res = auditPagesBarrelGovernance();
    expect(res.module).toBe('src/pages/index.ts');
    expect(res.phase).toBe('P142');
    expect(res.exportedPageCount).toBe(5);
    expect(res.lazyRoutesEnabled).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes exportedPageCount and lazyRoutesEnabled', () => {
    const res = auditPagesBarrelGovernance({
      exportedPageCount: 0,
      lazyRoutesEnabled: false,
    });
    expect(res.exportedPageCount).toBe(0);
    expect(res.lazyRoutesEnabled).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
