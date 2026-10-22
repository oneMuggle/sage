import { describe, expect, it } from 'vitest';

import {
  formatExcelPptEditFormJson,
  formatExcelPptEditFormSummary,
} from '../ExcelPptEditFormFields';

describe('ExcelPptEditFormFields audit helpers', () => {
  it('formats excel/ppt edit form summary', () => {
    expect(formatExcelPptEditFormSummary('excel', 3)).toBe(
      'docType=excel · sheets=3 · testId=office-edit-form-excel',
    );
    expect(formatExcelPptEditFormSummary('ppt', -1)).toBe(
      'docType=ppt · sheets=0 · testId=office-edit-form-ppt',
    );
  });

  it('exports excel/ppt edit form JSON snapshot', () => {
    expect(JSON.parse(formatExcelPptEditFormJson('excel', 2))).toEqual({
      docType: 'excel',
      sheetCount: 2,
      testId: 'office-edit-form-excel',
    });
  });
});

