import { describe, expect, it } from 'vitest';

import { evaluateQuestionBarrelGovernanceAudit } from '../index';

describe('evaluateQuestionBarrelGovernanceAudit (Phase P139)', () => {
  it('returns healthy report when QuestionDialog is exported from question barrel', () => {
    const report = evaluateQuestionBarrelGovernanceAudit({
      exportedSymbols: ['QuestionDialog'],
      hasQuestionDialogExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueSymbolCount).toBe(1);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty barrel and missing QuestionDialog export', () => {
    const report = evaluateQuestionBarrelGovernanceAudit({
      exportedSymbols: [],
      hasQuestionDialogExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'QUESTION_BARREL_EMPTY',
      'QUESTION_DIALOG_EXPORT_MISSING',
    ]);
  });
});
