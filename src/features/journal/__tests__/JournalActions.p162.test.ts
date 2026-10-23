import { describe, expect, it } from 'vitest';

import {
  auditJournalActionsGovernance,
  formatJournalActionsJson,
  formatJournalActionsSummary,
} from '../components/JournalActions';

describe('JournalActions Phase P162 governance audit', () => {
  it('audits JournalActions governance metadata', () => {
    const audit = auditJournalActionsGovernance('sess-p162', 'academic-publishing');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/journal/components/JournalActions.tsx');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('academic-publishing');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 JournalActions Governance');
  });

  it('preserves JournalActions summary and JSON helpers', () => {
    expect(formatJournalActionsSummary(true, false, false)).toContain('hasSpec=true');
    expect(formatJournalActionsJson(true, false, false)).toContain('hasSpec');
    const fallback = auditJournalActionsGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
