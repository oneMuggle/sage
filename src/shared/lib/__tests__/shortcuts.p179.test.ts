import { describe, expect, it } from 'vitest';

import {
  auditShortcutsGovernance,
  formatShortcutRegistryJson,
  formatShortcutRegistrySummary,
  SHORTCUT_GROUPS,
} from '../shortcuts';

describe('shortcuts P179 governance audit', () => {
  it('audits shortcuts governance contract and shortcut registry formatters', () => {
    const raw = auditShortcutsGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.shortcuts.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.groupCount).toBe(SHORTCUT_GROUPS.length);
    expect(formatShortcutRegistrySummary()).toContain(`groups=${SHORTCUT_GROUPS.length}`);
    expect(JSON.parse(formatShortcutRegistryJson()).groupCount).toBe(SHORTCUT_GROUPS.length);
  });
});
