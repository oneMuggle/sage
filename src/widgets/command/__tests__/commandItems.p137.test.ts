import { describe, expect, it } from 'vitest';

import { evaluateCommandItemsGovernanceAudit } from '../commandItems';

describe('evaluateCommandItemsGovernanceAudit (Phase P137)', () => {
  it('returns healthy report for unique command items with labels and conflict-free shortcuts', () => {
    const report = evaluateCommandItemsGovernanceAudit({
      itemIds: ['new-chat', 'toggle-sidebar', 'open-settings'],
      missingLabelCount: 0,
      missingShortcutConflictCount: 0,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueCommandCount).toBe(3);
    expect(report.hasDuplicateIds).toBe(false);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags duplicate command IDs, missing labels, and shortcut conflicts', () => {
    const report = evaluateCommandItemsGovernanceAudit({
      itemIds: ['new-chat', 'new-chat'],
      missingLabelCount: 1,
      missingShortcutConflictCount: 2,
    });
    expect(report.healthy).toBe(false);
    expect(report.hasDuplicateIds).toBe(true);
    expect(report.issueCodes).toEqual([
      'COMMAND_ITEMS_DUPLICATE_ID',
      'COMMAND_ITEMS_LABEL_MISSING',
      'COMMAND_ITEMS_SHORTCUT_CONFLICT',
    ]);
  });
});
