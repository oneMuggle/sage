import { describe, expect, it } from 'vitest';

import {
  evaluateRightPanelToggleAudit,
  exportRightPanelToggleAuditJson,
} from '../RightPanelToggle';

describe('RightPanelToggle audit diagnostics (Phase P135)', () => {
  it('validates healthy right panel toggle state', () => {
    const report = evaluateRightPanelToggleAudit({
      isOpen: true,
      activeTab: 'artifacts',
      badgeCount: 2,
      shortcutConfigured: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags missing tab, negative badge, and unconfigured shortcut', () => {
    const parsed = JSON.parse(
      exportRightPanelToggleAuditJson({
        isOpen: false,
        activeTab: ' ',
        badgeCount: -1,
        shortcutConfigured: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_right_panel_active_tab');
    expect(parsed.issueCodes).toContain('negative_badge_count');
    expect(parsed.issueCodes).toContain('missing_toggle_shortcut');
  });
});
