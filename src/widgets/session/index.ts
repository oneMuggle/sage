export { SessionList } from './SessionList';
export { SessionItem } from './SessionItem';
export { ArchivesModal } from './ArchivesModal';

export interface SessionBarrelAuditInput {
  exportedComponents: string[];
  hasSessionListExport: boolean;
  hasSessionItemExport: boolean;
  hasArchivesModalExport: boolean;
}

export interface SessionBarrelAuditReport {
  uniqueExportCount: number;
  completeSessionExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateSessionBarrelGovernanceAudit(
  input: SessionBarrelAuditInput,
): SessionBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedComponents
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueExportCount = new Set(normalized).size;
  if (uniqueExportCount < 3) {
    issueCodes.push('SESSION_BARREL_EXPORTS_LOW');
  }
  const completeSessionExports =
    input.hasSessionListExport && input.hasSessionItemExport && input.hasArchivesModalExport;
  if (!completeSessionExports) {
    issueCodes.push('SESSION_CORE_EXPORT_MISSING');
  }
  return {
    uniqueExportCount,
    completeSessionExports,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
