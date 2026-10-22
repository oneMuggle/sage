/**
 * Permission Widgets — M1 工具安全加固审批 UI
 */
export { ApprovalDialog } from './ApprovalDialog';
export { RemoteApprovalBridge } from './RemoteApprovalBridge';

export interface PermissionBarrelAuditInput {
  exportedComponents: string[];
  hasApprovalDialogExport: boolean;
  hasRemoteApprovalBridgeExport: boolean;
}

export interface PermissionBarrelAuditReport {
  uniqueExportCount: number;
  completePermissionExports: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluatePermissionBarrelGovernanceAudit(
  input: PermissionBarrelAuditInput,
): PermissionBarrelAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.exportedComponents
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
  const uniqueExportCount = new Set(normalized).size;
  if (uniqueExportCount < 2) {
    issueCodes.push('PERMISSION_BARREL_EXPORTS_LOW');
  }
  const completePermissionExports =
    input.hasApprovalDialogExport && input.hasRemoteApprovalBridgeExport;
  if (!completePermissionExports) {
    issueCodes.push('PERMISSION_CORE_EXPORT_MISSING');
  }
  return {
    uniqueExportCount,
    completePermissionExports,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
