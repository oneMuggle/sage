import { describe, expect, it } from 'vitest';

import {
  auditTextDiffGovernance,
  formatTextDiffJson,
  formatTextDiffSummary,
} from '../textDiff';

describe('textDiff P180 governance audit', () => {
  it('audits textDiff governance contract and span summary formatters', () => {
    const raw = auditTextDiffGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.text_diff.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.maxInputChars).toBeGreaterThan(0);
    expect(formatTextDiffSummary(null)).toBe('spans: 0 before · 0 after · 0 add · 0 del');
    expect(JSON.parse(formatTextDiffJson(null)).beforeCount).toBe(0);
  });
});
