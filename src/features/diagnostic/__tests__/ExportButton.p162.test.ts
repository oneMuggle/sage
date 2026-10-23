import { describe, expect, it } from 'vitest';

import {
  auditExportButtonGovernance,
  formatExportButtonAuditJson,
  formatExportButtonAuditSnapshot,
} from '../ExportButton';

describe('ExportButton Phase P162 governance audit', () => {
  it('audits ExportButton governance metadata', () => {
    const audit = auditExportButtonGovernance('sess-p162', 'diagnostics');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/diagnostic/ExportButton.tsx');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('diagnostics');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 ExportButton Governance');
  });

  it('preserves ExportButton snapshot and JSON helpers', () => {
    expect(formatExportButtonAuditSnapshot({ includePrompts: true, busy: false })).toContain('prompts=1');
    expect(formatExportButtonAuditJson({ includeHostname: true })).toContain('includeHostname');
    const fallback = auditExportButtonGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
