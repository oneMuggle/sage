import { describe, expect, it } from 'vitest';

import { evaluateEvolutionLogGovernanceAudit } from '../EvolutionLog';

describe('evaluateEvolutionLogGovernanceAudit (Phase P137)', () => {
  it('returns healthy report for valid page size, low failure rate, and responsive loading', () => {
    const report = evaluateEvolutionLogGovernanceAudit({
      entryCount: 20,
      pageSize: 20,
      failedEntryCount: 1,
      loadingStuckMs: 250,
    });
    expect(report.healthy).toBe(true);
    expect(report.failureRate).toBe(0.05);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags invalid page size, high failure rate, and stuck loading state', () => {
    const report = evaluateEvolutionLogGovernanceAudit({
      entryCount: 10,
      pageSize: 0,
      failedEntryCount: 8,
      loadingStuckMs: 25000,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'EVOLUTION_LOG_PAGE_SIZE_INVALID',
      'EVOLUTION_LOG_HIGH_FAILURE_RATE',
      'EVOLUTION_LOG_LOADING_STUCK',
    ]);
  });
});
