import { describe, expect, it } from 'vitest';

import {
  evaluateShikiCodeBlockAudit,
  exportShikiCodeBlockAuditJson,
} from '../ShikiCodeBlock';

describe('ShikiCodeBlock audit diagnostics (Phase P135)', () => {
  it('validates ready syntax-highlighted code block', () => {
    const report = evaluateShikiCodeBlockAudit({
      language: 'TypeScript',
      lineCount: 42,
      charCount: 1200,
      highlighterReady: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedLanguage).toBe('typescript');
  });

  it('flags empty content and fallback highlighter', () => {
    const parsed = JSON.parse(
      exportShikiCodeBlockAuditJson({
        language: '',
        lineCount: 0,
        charCount: 0,
        highlighterReady: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('empty_code_block_content');
    expect(parsed.issueCodes).toContain('shiki_highlighter_fallback');
  });
});
