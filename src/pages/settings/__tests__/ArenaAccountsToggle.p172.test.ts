import { describe, expect, it } from 'vitest';

import { auditArenaAccountsToggleGovernance } from '../ArenaAccountsToggle';

describe('auditArenaAccountsToggleGovernance (P172)', () => {
  it('returns compliant governance audit metadata for ArenaAccountsToggle', () => {
    const report = auditArenaAccountsToggleGovernance();
    expect(report.module).toBe('src/pages/settings/ArenaAccountsToggle.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('settings');
    expect(report.testId).toBe('toggle-arena-accounts');
    expect(report.compliant).toBe(true);
  });
});
