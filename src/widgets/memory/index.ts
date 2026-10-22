/**
 * Memory Widgets - Memory system UI components
 */
export { MemoryBrowser } from './MemoryBrowser';
export { MemoryItem } from './MemoryItem';
export { NewMemoryModal } from './NewMemoryModal';
export { ProjectProfileCard } from './ProjectProfileCard';
export { UserProfileCard } from './UserProfileCard';

export interface MemoryWidgetsBarrelAuditInput {
  exportedComponentNames: string[];
  hasMemoryBrowserExport: boolean;
  hasProfileCardExports: boolean;
}

export interface MemoryWidgetsBarrelAuditReport {
  uniqueExportCount: number;
  completeExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateMemoryWidgetsBarrelGovernanceAudit(
  input: MemoryWidgetsBarrelAuditInput,
): MemoryWidgetsBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedComponentNames
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueExportCount = new Set(normalized).size;
  if (uniqueExportCount < 4) {
    issueCodes.push('MEMORY_BARREL_EXPORTS_LOW');
  }
  if (!input.hasMemoryBrowserExport) {
    issueCodes.push('MEMORY_BROWSER_EXPORT_MISSING');
  }
  if (!input.hasProfileCardExports) {
    issueCodes.push('MEMORY_PROFILE_CARDS_EXPORT_MISSING');
  }
  return {
    uniqueExportCount,
    completeExports: input.hasMemoryBrowserExport && input.hasProfileCardExports,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
