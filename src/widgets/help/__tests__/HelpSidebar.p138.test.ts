import { describe, expect, it } from 'vitest';

import { evaluateHelpSidebarGovernanceAudit } from '../HelpSidebar';

describe('evaluateHelpSidebarGovernanceAudit (Phase P138)', () => {
  it('returns healthy report when help sidebar items are unique and active item resolves', () => {
    const report = evaluateHelpSidebarGovernanceAudit({
      itemIds: ['getting-started', 'shortcuts', 'faq'],
      activeItemId: 'shortcuts',
      searchQuery: '  keyboard ',
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueItemCount).toBe(3);
    expect(report.activeItemResolved).toBe(true);
    expect(report.normalizedSearchQuery).toBe('keyboard');
    expect(report.issueCodes).toEqual([]);
  });

  it('flags duplicate item IDs and unresolved active item ID', () => {
    const report = evaluateHelpSidebarGovernanceAudit({
      itemIds: ['faq', 'faq'],
      activeItemId: 'missing-topic',
      searchQuery: '',
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'HELP_SIDEBAR_DUPLICATE_ITEM_ID',
      'HELP_SIDEBAR_ACTIVE_ITEM_UNRESOLVED',
    ]);
  });
});
