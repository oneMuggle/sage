import { describe, expect, it } from 'vitest';

import { evaluateSessionBarrelGovernanceAudit } from '../index';

describe('evaluateSessionBarrelGovernanceAudit (Phase P139)', () => {
  it('returns healthy report when SessionList, SessionItem, and ArchivesModal are exported', () => {
    const report = evaluateSessionBarrelGovernanceAudit({
      exportedComponents: ['SessionList', 'SessionItem', 'ArchivesModal'],
      hasSessionListExport: true,
      hasSessionItemExport: true,
      hasArchivesModalExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueExportCount).toBe(3);
    expect(report.completeSessionExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags missing session barrel exports', () => {
    const report = evaluateSessionBarrelGovernanceAudit({
      exportedComponents: ['SessionList'],
      hasSessionListExport: true,
      hasSessionItemExport: false,
      hasArchivesModalExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'SESSION_BARREL_EXPORTS_LOW',
      'SESSION_CORE_EXPORT_MISSING',
    ]);
  });
});
