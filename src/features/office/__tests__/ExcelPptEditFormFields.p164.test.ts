import { describe, expect, it } from 'vitest';

import {
  auditExcelPptEditFormFieldsGovernance,
  formatExcelPptEditFormJson,
  formatExcelPptEditFormSummary,
} from '../ExcelPptEditFormFields';

describe('ExcelPptEditFormFields governance audit (P164)', () => {
  it('returns ready governance status for ExcelPptEditFormFields', () => {
    const snap = auditExcelPptEditFormFieldsGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/ExcelPptEditFormFields.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('formats excel/ppt edit form summary and json', () => {
    expect(formatExcelPptEditFormSummary('excel', 3)).toContain('docType=excel · sheets=3');
    expect(JSON.parse(formatExcelPptEditFormJson('ppt', 0))).toEqual({
      docType: 'ppt',
      sheetCount: 0,
      testId: 'office-edit-form-ppt',
    });
  });
});
