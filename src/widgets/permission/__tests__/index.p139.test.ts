import { describe, expect, it } from 'vitest';

import { evaluatePermissionBarrelGovernanceAudit } from '../index';

describe('evaluatePermissionBarrelGovernanceAudit (Phase P139)', () => {
  it('returns healthy report when ApprovalDialog and RemoteApprovalBridge are exported', () => {
    const report = evaluatePermissionBarrelGovernanceAudit({
      exportedComponents: ['ApprovalDialog', 'RemoteApprovalBridge'],
      hasApprovalDialogExport: true,
      hasRemoteApprovalBridgeExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueExportCount).toBe(2);
    expect(report.completePermissionExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags missing permission barrel exports', () => {
    const report = evaluatePermissionBarrelGovernanceAudit({
      exportedComponents: ['ApprovalDialog'],
      hasApprovalDialogExport: true,
      hasRemoteApprovalBridgeExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'PERMISSION_BARREL_EXPORTS_LOW',
      'PERMISSION_CORE_EXPORT_MISSING',
    ]);
  });
});
