import { describe, expect, it } from 'vitest';

import {
  auditMarkdownTextGovernance,
  buildMarkdownTextAuditJson,
  markdownToPlainText,
} from '../markdownText';

describe('markdownText Phase P160 governance audit', () => {
  it('audits markdownText governance metadata', () => {
    const audit = auditMarkdownTextGovernance('sess-p160', 'documentation');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/markdownText.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('documentation');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 MarkdownText Governance');
  });

  it('preserves markdownToPlainText and audit JSON helpers', () => {
    expect(markdownToPlainText('**Sage** [link](https://example.com)')).toContain('Sage');
    expect(buildMarkdownTextAuditJson('# Heading')).toContain('plainLength');
    const fallback = auditMarkdownTextGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
