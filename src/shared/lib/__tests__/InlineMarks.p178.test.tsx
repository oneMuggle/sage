import { describe, expect, it } from 'vitest';

import {
  auditInlineMarksGovernance,
  formatInlineMarksJson,
  formatInlineMarksSummary,
} from '../InlineMarks';

describe('InlineMarks P178 governance audit', () => {
  it('audits InlineMarks governance contract and inline mark counters', () => {
    const raw = auditInlineMarksGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.inline_marks.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.supportedMarks).toEqual(['**bold**', '*italic*']);
    expect(formatInlineMarksSummary('**b** *i*')).toBe('bold=1 · italic=1 · segments=3');
    expect(JSON.parse(formatInlineMarksJson('**b** *i*')).boldCount).toBe(1);
  });
});
