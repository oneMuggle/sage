import { describe, expect, it } from 'vitest';

import {
  auditUseJournalTemplatesGovernance,
  formatJournalTemplateDraftJson,
  formatJournalTemplateDraftSummary,
} from '../useJournalTemplates';

describe('useJournalTemplates Phase P162 governance audit', () => {
  it('audits useJournalTemplates governance metadata', () => {
    const audit = auditUseJournalTemplatesGovernance('sess-p162', 'academic-publishing');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/journal/useJournalTemplates.ts');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('academic-publishing');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 UseJournalTemplates Governance');
  });

  it('preserves journal template draft summary and JSON helpers', () => {
    const draft = {
      title: 'Sage Paper',
      authors: ['Alice'],
      abstract: 'Abstract text',
      keywords: ['AI'],
      sections: { intro: 'Hello' },
      references: ['Ref 1'],
    };
    expect(formatJournalTemplateDraftSummary(null, draft, [])).toContain('Sage Paper');
    expect(formatJournalTemplateDraftJson(null, draft, [])).toContain('Sage Paper');
    const fallback = auditUseJournalTemplatesGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
