import { describe, expect, it } from 'vitest';

import { evaluateWikiMarkdownPreviewGovernanceAudit } from '../MarkdownPreview';

describe('evaluateWikiMarkdownPreviewGovernanceAudit (Phase P140)', () => {
  it('returns healthy report when markdown preview is within byte limit and sanitized', () => {
    const report = evaluateWikiMarkdownPreviewGovernanceAudit({
      markdownContent: '# Project Wiki\nOverview and references.',
      maxPreviewBytes: 65536,
      sanitizeLinksEnabled: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.withinByteLimit).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags exceeded byte limit and disabled link sanitization', () => {
    const report = evaluateWikiMarkdownPreviewGovernanceAudit({
      markdownContent: 'x'.repeat(200),
      maxPreviewBytes: 50,
      sanitizeLinksEnabled: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'WIKI_MARKDOWN_PREVIEW_SIZE_EXCEEDED',
      'WIKI_MARKDOWN_PREVIEW_UNSANITIZED_LINKS',
    ]);
  });
});
