import { describe, expect, it } from 'vitest';

import {
  auditUnifiedDiffGovernance,
  formatUnifiedDiffJson,
  formatUnifiedDiffSummary,
} from '../unifiedDiff';

describe('unifiedDiff P180 governance audit', () => {
  it('audits unifiedDiff governance contract and diff summary helpers', () => {
    const raw = auditUnifiedDiffGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.unified_diff.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.sampleSummary).toContain('1 hunks · +1 / -1');
    expect(formatUnifiedDiffSummary('', 'A', 'B')).toBe('diff: A -> B · 0 hunks · +0 / -0');
    expect(JSON.parse(formatUnifiedDiffJson('')).isEmpty).toBe(true);
  });
});
