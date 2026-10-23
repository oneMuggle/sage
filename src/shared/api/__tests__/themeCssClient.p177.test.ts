import { describe, expect, it } from 'vitest';

import {
  auditThemeCssClientGovernance,
  formatThemeCssJson,
  formatThemeCssSummary,
} from '../themeCssClient';

describe('themeCssClient P177 governance audit', () => {
  it('audits themeCssClient governance contract and theme CSS formatters', () => {
    const raw = auditThemeCssClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.theme_css_client.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.methods).toEqual(['save', 'list', 'delete', 'get']);
    const sample = { id: 'c1', name: 'Nord', appearance: 'dark' as const, css: 'body{}' };
    expect(formatThemeCssSummary(sample)).toBe('Nord (c1) · dark · 6 chars');
    expect(JSON.parse(formatThemeCssJson(sample)).cssLength).toBe(6);
  });
});
