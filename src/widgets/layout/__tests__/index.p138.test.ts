import { describe, expect, it } from 'vitest';

import { evaluateLayoutBarrelGovernanceAudit } from '../index';

describe('evaluateLayoutBarrelGovernanceAudit (Phase P138)', () => {
  it('returns healthy report when all core layout barrel exports are present', () => {
    const report = evaluateLayoutBarrelGovernanceAudit({
      exportedComponentNames: ['Layout', 'Sidebar', 'Titlebar', 'TitlebarActions', 'WindowControls'],
      hasLayoutExport: true,
      hasSidebarExport: true,
      hasTitlebarExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueExportCount).toBe(5);
    expect(report.coreExportsComplete).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags incomplete barrel exports and missing core layout components', () => {
    const report = evaluateLayoutBarrelGovernanceAudit({
      exportedComponentNames: ['Layout'],
      hasLayoutExport: true,
      hasSidebarExport: false,
      hasTitlebarExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'LAYOUT_BARREL_EXPORTS_INCOMPLETE',
      'LAYOUT_BARREL_CORE_EXPORT_MISSING',
    ]);
  });
});
