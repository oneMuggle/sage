export { Layout } from './Layout';
export { Sidebar } from './Sidebar';
export { Titlebar } from './Titlebar';
export { TitlebarActions } from './TitlebarActions';
export { WindowControls } from './WindowControls';

export interface LayoutBarrelAuditInput {
  exportedComponentNames: string[];
  hasLayoutExport: boolean;
  hasSidebarExport: boolean;
  hasTitlebarExport: boolean;
}

export interface LayoutBarrelAuditReport {
  uniqueExportCount: number;
  coreExportsComplete: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateLayoutBarrelGovernanceAudit(
  input: LayoutBarrelAuditInput,
): LayoutBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedComponentNames
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueExportCount = new Set(normalized).size;
  if (uniqueExportCount < 3) {
    issueCodes.push('LAYOUT_BARREL_EXPORTS_INCOMPLETE');
  }
  const coreExportsComplete =
    input.hasLayoutExport && input.hasSidebarExport && input.hasTitlebarExport;
  if (!coreExportsComplete) {
    issueCodes.push('LAYOUT_BARREL_CORE_EXPORT_MISSING');
  }
  return {
    uniqueExportCount,
    coreExportsComplete,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
