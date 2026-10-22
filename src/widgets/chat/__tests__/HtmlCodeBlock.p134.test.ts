import { describe, expect, it } from 'vitest';

import {
  evaluateHtmlCodeBlockAudit,
  exportHtmlCodeBlockAuditJson,
} from '../HtmlCodeBlock';

describe('HtmlCodeBlock audit diagnostics (Phase P134)', () => {
  it('validates sandboxed HTML preview block', () => {
    const report = evaluateHtmlCodeBlockAudit({
      codeLength: 240,
      previewEnabled: true,
      sandboxed: true,
      containsScriptTag: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.safeToRender).toBe(true);
  });

  it('flags unsandboxed preview with script tag', () => {
    const parsed = JSON.parse(
      exportHtmlCodeBlockAuditJson({
        codeLength: 120,
        previewEnabled: true,
        sandboxed: false,
        containsScriptTag: true,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('unsandboxed_html_preview');
    expect(parsed.issueCodes).toContain('unsafe_script_execution_risk');
  });
});
