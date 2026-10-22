import { describe, expect, it } from 'vitest';

import { auditWikiStoreGovernance } from '../store';

describe('wiki store P157 governance audit', () => {
  it('returns healthy defaults for wiki store governance', () => {
    const res = auditWikiStoreGovernance();
    expect(res.module).toBe('src/entities/wiki/store.ts');
    expect(res.phase).toBe('P157');
    expect(res.pageCount).toBe(1);
    expect(res.activeSlug).toBe('index');
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when pageCount is 0', () => {
    const res = auditWikiStoreGovernance({ pageCount: 0 });
    expect(res.pageCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
