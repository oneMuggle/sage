import { describe, expect, it } from 'vitest';

import { evaluateHelpTabGovernanceAudit } from '../HelpTab';

describe('evaluateHelpTabGovernanceAudit (Phase P141)', () => {
  it('returns healthy report when help sections, shortcuts, and search filter are configured', () => {
    const report = evaluateHelpTabGovernanceAudit({
      guideSectionCount: 6,
      shortcutItemCount: 12,
      searchFilterEnabled: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.guideSectionCount).toBe(6);
    expect(report.shortcutItemCount).toBe(12);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty sections, negative shortcuts, and disabled search filter', () => {
    const report = evaluateHelpTabGovernanceAudit({
      guideSectionCount: 0,
      shortcutItemCount: -1,
      searchFilterEnabled: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'HELP_TAB_SECTIONS_EMPTY',
      'HELP_TAB_SHORTCUTS_NEGATIVE',
      'HELP_TAB_SEARCH_FILTER_DISABLED',
    ]);
  });
});
