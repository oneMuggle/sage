import { describe, expect, it } from 'vitest';

import {
  splitReviewSections,
  formatReviewSectionsSummary,
  formatReviewSectionsJson,
} from '../reviewSections';

describe('reviewSections audit helpers', () => {
  it('splits multi-file diff and formats summary and json', () => {
    const diff = [
      'diff --git a/src/a.ts b/src/a.ts',
      '--- a/src/a.ts',
      '+++ b/src/a.ts',
      '@@ -1 +1 @@',
      '-old',
      '+new',
    ].join('\n');
    const sections = splitReviewSections(diff);
    expect(formatReviewSectionsSummary(sections)).toBe('files=1 · binary=0 · lines=6');
    const parsed = JSON.parse(formatReviewSectionsJson(sections));
    expect(parsed).toEqual({
      fileCount: 1,
      binaryCount: 0,
      totalLines: 6,
      paths: ['src/a.ts'],
    });
  });

  it('handles empty or nullish sections safely', () => {
    expect(formatReviewSectionsSummary(null)).toBe('files=0 · binary=0 · lines=0');
    expect(JSON.parse(formatReviewSectionsJson(undefined)).fileCount).toBe(0);
  });
});
