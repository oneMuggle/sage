import { describe, expect, it } from 'vitest';

import {
  evaluateContextInputAudit,
  exportContextInputAuditJson,
} from '../ContextInput';

describe('ContextInput audit diagnostics (Phase P136)', () => {
  it('computes token usage percentage within budget', () => {
    const report = evaluateContextInputAudit({
      usedTokens: 32000,
      maxTokens: 128000,
      pinnedItemCount: 3,
      autoCompactEnabled: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.usagePct).toBe(25);
  });

  it('flags high context pressure without auto-compact', () => {
    const parsed = JSON.parse(
      exportContextInputAuditJson({
        usedTokens: 95000,
        maxTokens: 100000,
        pinnedItemCount: 1,
        autoCompactEnabled: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('high_context_pressure_without_autocompact');
  });
});
