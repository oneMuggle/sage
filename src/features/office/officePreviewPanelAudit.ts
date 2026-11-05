/**
 * Audit formatters for OfficePreviewPanel — factored out of
 * `OfficePreviewPanel.tsx` to keep that file under the architecture
 * `maxFileLines` ceiling. The formatters are pure functions used by
 * the "copy summary / copy JSON" buttons and by tests.
 */

import type { OfficeDocType } from '../../shared/api/types';

export function formatOfficePreviewPanelAuditSnapshot(input: {
  docType: OfficeDocType;
  filename: string;
  sizeBytes: number;
  fidelityOn: boolean;
  exporting: boolean;
}): string {
  const name = input.filename.trim() || '未命名';
  const sizeKb = (Math.max(0, input.sizeBytes) / 1024).toFixed(1);
  const viewLabel = input.fidelityOn ? '高保真视图' : '结构化视图';
  const exportLabel = input.exporting ? '导出中' : '就绪';
  return `文档预览 · ${input.docType.toUpperCase()} · ${name} · ${sizeKb}KB · ${viewLabel} · ${exportLabel}`;
}

export function formatOfficePreviewPanelAuditJson(input: {
  docType: OfficeDocType;
  filename: string;
  sizeBytes: number;
  fidelityOn: boolean;
  exporting: boolean;
}): string {
  return JSON.stringify({
    docType: input.docType,
    filename: input.filename.trim() || '未命名',
    sizeBytes: Math.max(0, Math.trunc(input.sizeBytes)),
    fidelityOn: Boolean(input.fidelityOn),
    exporting: Boolean(input.exporting),
  });
}
