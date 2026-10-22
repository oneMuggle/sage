import { describe, expect, it } from 'vitest';

import {
  evaluateSlashCommandMenuAudit,
  exportSlashCommandMenuAuditJson,
} from '../SlashCommandMenu';

describe('SlashCommandMenu audit diagnostics (Phase P135)', () => {
  it('validates in-bounds command selection', () => {
    const report = evaluateSlashCommandMenuAudit({
      query: '/compact',
      matchedCommandCount: 3,
      selectedIndex: 1,
      isOpen: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.selectionValid).toBe(true);
  });

  it('flags empty matches and out-of-bounds selection', () => {
    const parsed = JSON.parse(
      exportSlashCommandMenuAuditJson({
        query: '/unknown',
        matchedCommandCount: 0,
        selectedIndex: 2,
        isOpen: true,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('no_matching_slash_commands');
    expect(parsed.issueCodes).toContain('slash_menu_selection_out_of_bounds');
  });
});
