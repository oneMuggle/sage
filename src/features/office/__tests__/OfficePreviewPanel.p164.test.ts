import { describe, expect, it } from 'vitest';

import {
  auditOfficePreviewPanelGovernance,
  formatOfficePreviewPanelAuditJson,
  formatOfficePreviewPanelAuditSnapshot,
} from '../OfficePreviewPanel';

describe('OfficePreviewPanel governance audit (P164)', () => {
  it('returns ready governance status for OfficePreviewPanel', () => {
    const snap = auditOfficePreviewPanelGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/OfficePreviewPanel.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('formats office preview panel audit snapshot and json', () => {
    const input = {
      docType: 'word' as const,
      filename: 'spec.docx',
      sizeBytes: 2048,
      fidelityOn: true,
      exporting: false,
    };
    expect(formatOfficePreviewPanelAuditSnapshot(input)).toContain('WORD · spec.docx');
    expect(JSON.parse(formatOfficePreviewPanelAuditJson(input))).toEqual({
      docType: 'word',
      filename: 'spec.docx',
      sizeBytes: 2048,
      fidelityOn: true,
      exporting: false,
    });
  });
});
