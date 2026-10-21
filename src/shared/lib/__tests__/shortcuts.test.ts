import { describe, expect, it } from 'vitest';

import {
  SHORTCUT_GROUPS,
  formatShortcutRegistryJson,
  formatShortcutRegistrySummary,
} from '../shortcuts';

describe('shortcuts audit diagnostics', () => {
  it('formats shortcut registry summary', () => {
    const expectedTotal = SHORTCUT_GROUPS.reduce((sum, g) => sum + g.items.length, 0);
    expect(formatShortcutRegistrySummary()).toBe(
      `groups=${SHORTCUT_GROUPS.length} · shortcuts=${expectedTotal}`,
    );
    expect(formatShortcutRegistrySummary([])).toBe('groups=0 · shortcuts=0');
  });

  it('serializes shortcut registry audit JSON', () => {
    const expectedTotal = SHORTCUT_GROUPS.reduce((sum, g) => sum + g.items.length, 0);
    const parsed = JSON.parse(formatShortcutRegistryJson());
    expect(parsed).toEqual({
      groupCount: 5,
      totalShortcuts: expectedTotal,
      groupNames: ['全局', '消息输入', '会话内查找', '输入框 Emacs 键位', '审批对话框'],
    });
  });
});
