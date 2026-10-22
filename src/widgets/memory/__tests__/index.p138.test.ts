import { describe, expect, it } from 'vitest';

import { evaluateMemoryWidgetsBarrelGovernanceAudit } from '../index';

describe('evaluateMemoryWidgetsBarrelGovernanceAudit (Phase P138)', () => {
  it('returns healthy report when all memory widget barrel exports are present', () => {
    const report = evaluateMemoryWidgetsBarrelGovernanceAudit({
      exportedComponentNames: [
        'MemoryBrowser',
        'MemoryItem',
        'NewMemoryModal',
        'ProjectProfileCard',
        'UserProfileCard',
      ],
      hasMemoryBrowserExport: true,
      hasProfileCardExports: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueExportCount).toBe(5);
    expect(report.completeExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags missing memory browser and profile card exports', () => {
    const report = evaluateMemoryWidgetsBarrelGovernanceAudit({
      exportedComponentNames: ['MemoryItem'],
      hasMemoryBrowserExport: false,
      hasProfileCardExports: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'MEMORY_BARREL_EXPORTS_LOW',
      'MEMORY_BROWSER_EXPORT_MISSING',
      'MEMORY_PROFILE_CARDS_EXPORT_MISSING',
    ]);
  });
});
