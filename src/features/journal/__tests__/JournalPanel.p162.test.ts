import { describe, expect, it } from 'vitest';

import {
  auditJournalPanelGovernance,
  formatJournalPanelJson,
  formatJournalPanelSummary,
} from '../JournalPanel';

describe('JournalPanel Phase P162 governance audit', () => {
  it('audits JournalPanel governance metadata', () => {
    const audit = auditJournalPanelGovernance('sess-p162', 'academic-publishing');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/journal/JournalPanel.tsx');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('academic-publishing');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 JournalPanel Governance');
  });

  it('preserves JournalPanel summary and JSON helpers', () => {
    expect(formatJournalPanelSummary('/workspace/paper', 1, 2)).toContain('bound');
    expect(formatJournalPanelJson('/workspace/paper', 1, 2)).toContain('workspaceBound');
    const fallback = auditJournalPanelGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
