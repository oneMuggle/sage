import { describe, expect, it } from 'vitest';

import {
  auditUseNavigationHistoryGovernance,
  formatNavHistoryJson,
  formatNavHistorySummary,
} from '../useNavigationHistory';

describe('useNavigationHistory P180 governance audit', () => {
  it('audits useNavigationHistory governance contract and context formatters', () => {
    const raw = auditUseNavigationHistoryGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.use_navigation_history.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.unavailableSummary).toBe('nav-history: unavailable');
    expect(formatNavHistorySummary(null)).toBe('nav-history: unavailable');
    expect(JSON.parse(formatNavHistoryJson(null)).available).toBe(false);
  });
});
