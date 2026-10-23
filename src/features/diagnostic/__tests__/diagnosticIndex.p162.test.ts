import { describe, expect, it } from 'vitest';

import {
  auditDiagnosticBarrelGovernance,
  formatDiagnosticFeatureBarrelJson,
  formatDiagnosticFeatureBarrelSummary,
} from '../index';

describe('diagnostic barrel Phase P162 governance audit', () => {
  it('audits diagnostic barrel governance metadata', () => {
    const audit = auditDiagnosticBarrelGovernance('sess-p162', 'diagnostics');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/diagnostic/index.ts');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('diagnostics');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 DiagnosticBarrel Governance');
  });

  it('preserves diagnostic barrel summary and JSON helpers', () => {
    expect(formatDiagnosticFeatureBarrelSummary()).toContain('DiagnosticCard');
    expect(formatDiagnosticFeatureBarrelJson()).toContain('features/diagnostic');
    const fallback = auditDiagnosticBarrelGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
