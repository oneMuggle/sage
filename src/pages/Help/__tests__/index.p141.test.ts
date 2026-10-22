import { describe, expect, it } from 'vitest';

import { evaluateHelpPageContainerGovernanceAudit } from '../index';

describe('evaluateHelpPageContainerGovernanceAudit (Phase P141)', () => {
  it('returns healthy report when help page container has all sub-tabs and switch handler', () => {
    const report = evaluateHelpPageContainerGovernanceAudit({
      activeSubTab: 'help',
      availableSubTabs: ['help', 'changelog', 'about'],
      hasTabSwitchHandler: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.activeSubTabValid).toBe(true);
    expect(report.subTabCount).toBe(3);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags incomplete sub-tabs, invalid active sub-tab, and missing switch handler', () => {
    const report = evaluateHelpPageContainerGovernanceAudit({
      activeSubTab: 'missing',
      availableSubTabs: ['help'],
      hasTabSwitchHandler: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'HELP_PAGE_SUBTABS_INCOMPLETE',
      'HELP_PAGE_ACTIVE_SUBTAB_INVALID',
      'HELP_PAGE_TAB_SWITCH_HANDLER_MISSING',
    ]);
  });
});
