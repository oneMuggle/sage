import { describe, expect, it } from 'vitest';

import { auditThemeSelectorGovernance } from '../ThemeSelector';

describe('auditThemeSelectorGovernance (P173)', () => {
  it('returns compliant governance audit metadata for ThemeSelector', () => {
    const report = auditThemeSelectorGovernance();
    expect(report.module).toBe('src/pages/settings/ThemeSelector.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('settings');
    expect(report.supportsCustomCssThemesAndModal).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
