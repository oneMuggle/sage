import { describe, expect, it } from 'vitest';

import {
  auditJournalValidationReportGovernance,
  formatJournalValidationJson,
  formatJournalValidationMarkdown,
} from '../components/JournalValidationReport';

describe('JournalValidationReport governance audit (P163)', () => {
  it('returns ready governance status for JournalValidationReport', () => {
    const snap = auditJournalValidationReportGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/journal/components/JournalValidationReport.tsx',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats empty journal validation markdown and json', () => {
    expect(formatJournalValidationMarkdown([], 0, 0)).toContain('_无违规项_');
    expect(JSON.parse(formatJournalValidationJson([], 0, 0))).toMatchObject({
      errorCount: 0,
      warningCount: 0,
      total: 0,
    });
  });
});
