import { describe, expect, it } from 'vitest';

import {
  auditUseDiagnosticPreviewGovernance,
  formatDiagnosticPreviewJson,
  formatDiagnosticPreviewSummary,
} from '../useDiagnosticPreview';

describe('useDiagnosticPreview Phase P162 governance audit', () => {
  it('audits useDiagnosticPreview governance metadata', () => {
    const audit = auditUseDiagnosticPreviewGovernance('sess-p162', 'diagnostics');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/diagnostic/useDiagnosticPreview.ts');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('diagnostics');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 UseDiagnosticPreview Governance');
  });

  it('preserves diagnostic preview summary and JSON helpers', () => {
    expect(formatDiagnosticPreviewSummary({ count: 5, version: '1.0.0' })).toContain('1.0.0');
    expect(formatDiagnosticPreviewJson({ count: 5, sampleUrls: ['u1'] })).toContain('sampleCount');
    const fallback = auditUseDiagnosticPreviewGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
