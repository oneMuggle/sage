import { describe, expect, it } from 'vitest';

import {
  auditDiagnosticCardGovernance,
  formatDiagnosticPreviewJson,
  formatDiagnosticPreviewMarkdown,
} from '../DiagnosticCard';

describe('DiagnosticCard Phase P162 governance audit', () => {
  it('audits DiagnosticCard governance metadata with explicit session and archetype', () => {
    const audit = auditDiagnosticCardGovernance('sess-p162', 'diagnostics');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/diagnostic/DiagnosticCard.tsx');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('diagnostics');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 DiagnosticCard Governance');
  });

  it('preserves diagnostic preview markdown and JSON helpers', () => {
    const sample = { count: 3, sampleUrls: ['https://api.example.com'] };
    expect(formatDiagnosticPreviewMarkdown(sample, true, false)).toContain('3');
    expect(formatDiagnosticPreviewJson(sample, true, false)).toContain('api.example.com');
    const fallback = auditDiagnosticCardGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
