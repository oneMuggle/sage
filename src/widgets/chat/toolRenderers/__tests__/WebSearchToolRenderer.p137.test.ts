import { describe, expect, it } from 'vitest';

import { evaluateWebSearchToolRendererGovernanceAudit } from '../WebSearchToolRenderer';

describe('evaluateWebSearchToolRendererGovernanceAudit (Phase P137)', () => {
  it('returns healthy report for completed search with valid query and latency', () => {
    const report = evaluateWebSearchToolRendererGovernanceAudit({
      queryText: 'typescript strict mode',
      resultCount: 5,
      searchCompleted: true,
      latencyMs: 420,
    });
    expect(report.healthy).toBe(true);
    expect(report.hasQuery).toBe(true);
    expect(report.normalizedResultCount).toBe(5);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty query, negative result count, incomplete search, and excessive latency', () => {
    const report = evaluateWebSearchToolRendererGovernanceAudit({
      queryText: '   ',
      resultCount: -2,
      searchCompleted: false,
      latencyMs: 95000,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'WEB_SEARCH_QUERY_EMPTY',
      'WEB_SEARCH_RESULT_COUNT_NEGATIVE',
      'WEB_SEARCH_INCOMPLETE',
      'WEB_SEARCH_LATENCY_OUT_OF_RANGE',
    ]);
  });
});
