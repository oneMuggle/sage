import { describe, expect, it } from 'vitest';

import { evaluateSidebarNavItemGovernanceAudit } from '../SidebarNavItem';

describe('evaluateSidebarNavItemGovernanceAudit (Phase P138)', () => {
  it('returns healthy report for valid nav item ID, label, and badge count', () => {
    const report = evaluateSidebarNavItemGovernanceAudit({
      itemId: 'workbench',
      label: 'Workbench',
      badgeCount: 3,
      disabled: false,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedId).toBe('workbench');
    expect(report.normalizedBadgeCount).toBe(3);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty ID, empty label, and negative badge count', () => {
    const report = evaluateSidebarNavItemGovernanceAudit({
      itemId: '  ',
      label: '',
      badgeCount: -4,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'SIDEBAR_NAV_ITEM_ID_EMPTY',
      'SIDEBAR_NAV_ITEM_LABEL_EMPTY',
      'SIDEBAR_NAV_ITEM_BADGE_NEGATIVE',
    ]);
  });
});
