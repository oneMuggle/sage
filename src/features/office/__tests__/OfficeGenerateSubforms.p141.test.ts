import { describe, expect, it } from 'vitest';

import { evaluateOfficeGenerateSubformsGovernanceAudit } from '../OfficeGenerateSubforms';

describe('evaluateOfficeGenerateSubformsGovernanceAudit (Phase P141)', () => {
  it('returns healthy report for supported office document subform state', () => {
    const report = evaluateOfficeGenerateSubformsGovernanceAudit({
      docType: 'word',
      templateLoadState: 'ready',
      templateCount: 6,
      selectedTemplateId: 'tpl-report',
    });
    expect(report.healthy).toBe(true);
    expect(report.isSupportedTemplateDocType).toBe(true);
    expect(report.templateCount).toBe(6);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags unsupported docType, error load state, and negative template count', () => {
    const report = evaluateOfficeGenerateSubformsGovernanceAudit({
      docType: 'pdf',
      templateLoadState: 'error',
      templateCount: -2,
      selectedTemplateId: '',
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'OFFICE_SUBFORM_DOC_TYPE_UNSUPPORTED',
      'OFFICE_SUBFORM_TEMPLATE_LOAD_ERROR',
      'OFFICE_SUBFORM_TEMPLATE_COUNT_NEGATIVE',
    ]);
  });
});
