import { describe, expect, it } from 'vitest';

import {
  auditPdfFormFillDialog,
  exportPdfFormFillDialogAuditJson,
} from '../PdfFormFillDialog';

describe('PdfFormFillDialog audit diagnostics', () => {
  it('audits field count and filling state', () => {
    const def = auditPdfFormFillDialog();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/features/office/PdfFormFillDialog.tsx');
    expect(def.fieldCount).toBe(0);
    expect(def.isFilling).toBe(false);
    expect(def.hasSubmitButton).toBe(true);

    const filling = auditPdfFormFillDialog(-1, true);
    expect(filling.fieldCount).toBe(0);
    expect(filling.isFilling).toBe(true);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportPdfFormFillDialogAuditJson(6, true));
    expect(parsed.componentName).toBe('PdfFormFillDialog');
    expect(parsed.fieldCount).toBe(6);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
