import { describe, expect, it } from 'vitest';

import {
  auditFillTemplateGovernance,
  fillTemplate,
  formatFillTemplateJson,
  formatFillTemplateSummary,
} from '../fillTemplate';

describe('fillTemplate P178 governance audit', () => {
  it('audits fillTemplate governance contract and placeholder replacement', () => {
    const raw = auditFillTemplateGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.fill_template.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.sampleResult).toBe('Hello Sage');
    expect(fillTemplate('{a}-{b}', { a: 1 })).toBe('1-{b}');
    expect(formatFillTemplateSummary('{a}-{b}', { a: 1 })).toBe(
      'placeholders=2 · filled=1 · unresolved=1',
    );
    expect(JSON.parse(formatFillTemplateJson('{a}', { a: 'x' })).result).toBe('x');
  });
});
