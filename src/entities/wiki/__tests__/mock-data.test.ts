import { describe, expect, it } from 'vitest';

import {
  formatWikiMockDataJson,
  formatWikiMockDataSummary,
  mockLintItems,
  mockReviewItems,
} from '../mock-data';

describe('wiki mock-data audit helpers', () => {
  it('formats mock dataset summary', () => {
    expect(mockLintItems.length).toBeGreaterThan(0);
    expect(mockReviewItems.length).toBeGreaterThan(0);
    expect(formatWikiMockDataSummary()).toBe(
      'lint=4 · reviews=5 · activities=4 · research=2',
    );
  });

  it('serializes mock dataset audit JSON', () => {
    expect(JSON.parse(formatWikiMockDataJson())).toEqual({
      lintCount: 4,
      reviewCount: 5,
      sourceRootCount: 1,
      activityCount: 4,
      researchCount: 2,
    });
  });
});
