import { describe, expect, it } from 'vitest';

import {
  auditJournalBarrelGovernance,
  formatJournalBarrelJson,
  formatJournalBarrelSummary,
} from '../index';

describe('journal barrel Phase P162 governance audit', () => {
  it('audits journal barrel governance metadata', () => {
    const audit = auditJournalBarrelGovernance('sess-p162', 'academic-publishing');
    expect(audit.phase).toBe('P162');
    expect(audit.module).toBe('src/features/journal/index.ts');
    expect(audit.sessionId).toBe('sess-p162');
    expect(audit.archetype).toBe('academic-publishing');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P162 JournalBarrel Governance');
  });

  it('preserves journal barrel summary and JSON helpers', () => {
    expect(formatJournalBarrelSummary()).toContain('JournalPanel');
    expect(formatJournalBarrelJson()).toContain('features/journal');
    const fallback = auditJournalBarrelGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
