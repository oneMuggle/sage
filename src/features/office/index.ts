export { useOfficeDocuments } from './useOfficeDocuments';
export type {
  OfficeReadResult,
  OfficeListView,
  OfficeMultiImportResult,
  OfficeMultiImportEntry,
  OfficeMultiImportSkipped,
  OfficeDuplicateChoice,
  OfficePendingDuplicate,
} from './useOfficeDocuments';
export { OfficeIntake } from './OfficeIntake';
export { OfficePreviewPanel } from './OfficePreviewPanel';
export type { OfficePreviewData } from './OfficePreviewPanel';
export { DocumentAuditPanel } from './DocumentAuditPanel';
export { OfficeDocumentList } from './OfficeDocumentList';
export { OfficeSnapshotPanel } from './OfficeSnapshotPanel';
export { OfficeEditPreviewDialog } from './OfficeEditPreviewDialog';
export { buildUpdateOps } from './OfficeEditPreviewDialog';
export { OfficeDuplicateDialog } from './OfficeDuplicateDialog';
export { OfficeGenerateForm } from './OfficeGenerateForm';
export { GenerateWorkspace } from './GenerateWorkspace';
export { TemplateLibrary } from './TemplateLibrary';
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
    'OfficeIntake',
    'OfficePreviewPanel',
    'DocumentAuditPanel',
    'OfficeDocumentList',
    'OfficeSnapshotPanel',
    'OfficeEditPreviewDialog',
    'buildUpdateOps',
    'OfficeDuplicateDialog',
    'OfficeGenerateForm',
    'OfficeCapabilityBar',
    'WordPreview',
    'ExcelPreview',
    'PptPreview',
    'GenerateWorkspace',
    'TemplateLibrary',
  ] as const;
  return {
    schemaVersion: '1.0',
    module: 'src/features/office/index.ts',
    exportedSymbols,
    symbolCount: exportedSymbols.length,
    exportedAt: '2026-11-07',
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
