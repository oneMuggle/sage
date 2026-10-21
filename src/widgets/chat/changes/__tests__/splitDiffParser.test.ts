import { describe, expect, it } from 'vitest';

import {
  parseUnifiedDiff,
  formatSplitDiffSummary,
  formatSplitDiffJson,
} from '../splitDiffParser';

describe('splitDiffParser audit helpers', () => {
  it('parses unified diff and formats split diff summary and json', () => {
    const diff = [
      'diff --git a/a.ts b/a.ts',
      '@@ -1,2 +1,3 @@',
      ' line1',
      '-old2',
      '+new2',
      '+added3',
    ].join('\n');
    const rows = parseUnifiedDiff(diff);
    expect(formatSplitDiffSummary(rows)).toBe(
      'rows=5 · modify=1 · add=1 · remove=0 · context=1',
    );
    const parsed = JSON.parse(formatSplitDiffJson(rows));
    expect(parsed).toEqual({
      totalRows: 5,
      modify: 1,
      add: 1,
      remove: 0,
      context: 1,
      header: 2,
    });
  });

  it('handles empty or nullish rows safely', () => {
    expect(formatSplitDiffSummary(null)).toBe(
      'rows=0 · modify=0 · add=0 · remove=0 · context=0',
    );
    expect(JSON.parse(formatSplitDiffJson(undefined)).totalRows).toBe(0);
  });
});
