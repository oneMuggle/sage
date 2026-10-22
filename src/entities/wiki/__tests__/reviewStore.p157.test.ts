import { describe, expect, it } from 'vitest';

import { auditWikiReviewStoreGovernance } from '../review-store';

describe('wiki review-store P157 governance audit', () => {
  it('returns healthy defaults for wiki review-store governance', () => {
    const res = auditWikiReviewStoreGovernance();
    expect(res.module).toBe('src/entities/wiki/review-store.ts');
    expect(res.phase).toBe('P157');
    expect(res.pendingReviewCount).toBe(0);
    expect(res.rejectedCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when pendingReviewCount exceeds 500', () => {
    const res = auditWikiReviewStoreGovernance({
      pendingReviewCount: 600,
      rejectedCount: 2,
    });
    expect(res.pendingReviewCount).toBe(600);
    expect(res.rejectedCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
