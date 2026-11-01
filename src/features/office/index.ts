export { useOfficeDocuments } from './useOfficeDocuments';
<<<<<<< HEAD
export type { OfficeReadResult, OfficeListView } from './useOfficeDocuments';;
export { OfficeFilePicker } from './OfficeFilePicker';
export { OfficePreviewPanel } from './OfficePreviewPanel';
export type { OfficePreviewData } from './OfficePreviewPanel';
export { OfficeDocumentList } from './OfficeDocumentList';
export { OfficeSnapshotPanel } from './OfficeSnapshotPanel';
export { OfficeEditPreviewDialog } from './OfficeEditPreviewDialog';
;
=======
export type { OfficeReadResult, OfficeListView } from './useOfficeDocuments';
export { OfficeFilePicker } from './OfficeFilePicker';
export { OfficePreviewPanel } from './OfficePreviewPanel';
export type { OfficePreviewData } from './OfficePreviewPanel';
export { DocumentAuditPanel } from './DocumentAuditPanel';
export { OfficeDocumentList } from './OfficeDocumentList';
export { OfficeSnapshotPanel } from './OfficeSnapshotPanel';
export { OfficeEditPreviewDialog } from './OfficeEditPreviewDialog';
>>>>>>> origin/main
export { buildUpdateOps } from './OfficeEditPreviewDialog';
export { OfficeGenerateForm } from './OfficeGenerateForm';
export { OfficeCapabilityBar } from './OfficeCapabilityBar';
// Round B P3: structured sub-previews shared with the chat ArtifactViewer.
export { WordPreview, ExcelPreview, PptPreview } from './OfficePreviewPanel';

export interface OfficeFeatureBarrelAuditReport {
  schemaVersion: '1.0';
  module: 'src/features/office/index.ts';
  exportedSymbols: readonly string[];
  symbolCount: number;
  exportedAt: string;
}

export function auditOfficeFeatureBarrel(): OfficeFeatureBarrelAuditReport {
  const exportedSymbols = [
    'useOfficeDocuments',
    'OfficeFilePicker',
    'OfficePreviewPanel',
<<<<<<< HEAD
=======
    'DocumentAuditPanel',
>>>>>>> origin/main
    'OfficeDocumentList',
    'OfficeSnapshotPanel',
    'OfficeEditPreviewDialog',
    'buildUpdateOps',
    'OfficeGenerateForm',
    'OfficeCapabilityBar',
    'WordPreview',
    'ExcelPreview',
    'PptPreview',
  ] as const;
  return {
    schemaVersion: '1.0',
    module: 'src/features/office/index.ts',
    exportedSymbols,
    symbolCount: exportedSymbols.length,
    exportedAt: '2026-10-22',
  };
}

export function exportOfficeFeatureBarrelAuditJson(): string {
  return JSON.stringify(auditOfficeFeatureBarrel(), null, 2);
}

export function auditOfficeFeatureBarrelGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/index.ts',
    phase: 'P165',
    status: 'ready',
  };
}
