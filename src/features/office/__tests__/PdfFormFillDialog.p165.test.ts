import { describe, expect, it } from 'vitest';

import {
  auditPdfFormFillDialog,
  auditPdfFormFillDialogGovernance,
  exportPdfFormFillDialogAuditJson,
} from '../PdfFormFillDialog';

describe('PdfFormFillDialog governance audit (P165)', () => {
  it('returns ready governance status for PdfFormFillDialog', () => {
    const snap = auditPdfFormFillDialogGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/PdfFormFillDialog.tsx',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('audits pdf form fill dialog report and json', () => {
    expect(auditPdfFormFillDialog(3, true).fieldCount).toBe(3);
    expect(JSON.parse(exportPdfFormFillDialogAuditJson(2, false)).fieldCount).toBe(2);
  });
});
