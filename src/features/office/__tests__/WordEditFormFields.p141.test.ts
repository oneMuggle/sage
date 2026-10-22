import { describe, expect, it } from 'vitest';

import { evaluateWordEditFormFieldsGovernanceAudit } from '../WordEditFormFields';

describe('evaluateWordEditFormFieldsGovernanceAudit (Phase P141)', () => {
  it('returns healthy report for valid .docx target and replacement rules', () => {
    const report = evaluateWordEditFormFieldsGovernanceAudit({
      operationMode: 'replace',
      targetPath: '/docs/proposal.docx',
      replacementRuleCount: 3,
      hasInstructionText: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.hasDocxExtension).toBe(true);
    expect(report.normalizedReplacementRuleCount).toBe(3);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags non-docx path, negative rule count, and empty edit action', () => {
    const report = evaluateWordEditFormFieldsGovernanceAudit({
      operationMode: 'replace',
      targetPath: '/docs/legacy.doc',
      replacementRuleCount: -1,
      hasInstructionText: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'WORD_EDIT_TARGET_NOT_DOCX',
      'WORD_EDIT_RULE_COUNT_NEGATIVE',
      'WORD_EDIT_ACTION_EMPTY',
    ]);
  });
});
