import { describe, expect, it } from 'vitest';

import {
  auditModelWindowsGovernance,
  DEFAULT_CONTEXT_WINDOW_TOKENS,
  formatModelWindowJson,
  formatModelWindowSummary,
  historyBudgetFor,
} from '../modelWindows';

describe('modelWindows P179 governance audit', () => {
  it('audits modelWindows governance contract and window budget helpers', () => {
    const raw = auditModelWindowsGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.model_windows.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.defaultContextWindowTokens).toBe(DEFAULT_CONTEXT_WINDOW_TOKENS);
    expect(historyBudgetFor(100000, 10000)).toBe(90000);
    expect(formatModelWindowSummary(64000, null, true, 4000)).toContain('window=64000');
    expect(JSON.parse(formatModelWindowJson(64000, null, true, 4000)).historyBudget).toBe(60000);
  });
});
