import { describe, expect, it } from 'vitest';

import {
  auditWikiMockDataGovernance,
  mockLintItems,
  mockReviewItems,
} from '../mock-data';

describe('wiki mock-data P156 governance audit', () => {
  it('returns healthy defaults for wiki mock-data governance', () => {
    const res = auditWikiMockDataGovernance();
    expect(res.module).toBe('src/entities/wiki/mock-data.ts');
    expect(res.phase).toBe('P156');
    expect(res.lintCount).toBe(mockLintItems.length);
    expect(res.reviewCount).toBe(mockReviewItems.length);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when lintCount or reviewCount is 0', () => {
    const res = auditWikiMockDataGovernance({
      lintCount: 0,
      reviewCount: 0,
    });
    expect(res.lintCount).toBe(0);
    expect(res.reviewCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
