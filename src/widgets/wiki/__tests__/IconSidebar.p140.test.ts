import { describe, expect, it } from 'vitest';

import { evaluateWikiIconSidebarGovernanceAudit } from '../IconSidebar';

describe('evaluateWikiIconSidebarGovernanceAudit (Phase P140)', () => {
  it('returns healthy report for valid wiki icon sidebar tabs and badge counts', () => {
    const report = evaluateWikiIconSidebarGovernanceAudit({
      activeTab: 'files',
      availableTabs: ['files', 'sources', 'graph', 'lint'],
      badgeCountByTab: { lint: 3, sources: 1 },
    });
    expect(report.healthy).toBe(true);
    expect(report.activeTabValid).toBe(true);
    expect(report.totalBadgeCount).toBe(4);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty tabs, invalid active tab, and negative badge count', () => {
    const report = evaluateWikiIconSidebarGovernanceAudit({
      activeTab: 'unknown',
      availableTabs: [],
      badgeCountByTab: { lint: -2 },
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'WIKI_ICON_SIDEBAR_TABS_EMPTY',
      'WIKI_ICON_SIDEBAR_ACTIVE_TAB_INVALID',
      'WIKI_ICON_SIDEBAR_BADGE_NEGATIVE',
    ]);
  });
});
