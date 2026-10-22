import { describe, expect, it } from 'vitest';

import { evaluateEvolutionPanelGovernanceAudit } from '../EvolutionPanel';

describe('evaluateEvolutionPanelGovernanceAudit (Phase P137)', () => {
  it('returns healthy report for standard 60s refresh interval and active background cron', () => {
    const report = evaluateEvolutionPanelGovernanceAudit({
      refreshIntervalMs: 60000,
      recentLogLimit: 10,
      backgroundCronActive: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags overly aggressive refresh interval, invalid log limit, and inactive cron', () => {
    const report = evaluateEvolutionPanelGovernanceAudit({
      refreshIntervalMs: 1000,
      recentLogLimit: 0,
      backgroundCronActive: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'EVOLUTION_PANEL_REFRESH_TOO_FAST',
      'EVOLUTION_PANEL_LOG_LIMIT_OUT_OF_RANGE',
      'EVOLUTION_PANEL_CRON_INACTIVE',
    ]);
  });
});
