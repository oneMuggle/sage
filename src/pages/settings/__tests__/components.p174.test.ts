import { describe, expect, it } from 'vitest';

import { auditSettingsComponentsGovernance } from '../components';

describe('auditSettingsComponentsGovernance (P174)', () => {
  it('returns compliant governance audit metadata for settings components', () => {
    const report = auditSettingsComponentsGovernance();
    expect(report.module).toBe('src/pages/settings/components.tsx');
    expect(report.phase).toBe('P174');
    expect(report.domain).toBe('settings');
    expect(report.exportsAdvancedSectionAndSettingRow).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
