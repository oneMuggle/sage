import { describe, expect, it } from 'vitest';

import { auditFontSettingsSectionGovernance } from '../FontSettingsSection';

describe('FontSettingsSection P143 governance audit', () => {
  it('returns healthy defaults for FontSettingsSection governance', () => {
    const res = auditFontSettingsSectionGovernance();
    expect(res.module).toBe('src/pages/settings/FontSettingsSection.tsx');
    expect(res.phase).toBe('P143');
    expect(res.fontScalePercent).toBe(100);
    expect(res.minScalePercent).toBe(85);
    expect(res.maxScalePercent).toBe(130);
    expect(res.healthy).toBe(true);
  });

  it('clamps fontScalePercent within min and max bounds', () => {
    const res = auditFontSettingsSectionGovernance({
      fontScalePercent: 180,
      minScalePercent: 90,
      maxScalePercent: 125,
    });
    expect(res.fontScalePercent).toBe(125);
    expect(res.minScalePercent).toBe(90);
    expect(res.maxScalePercent).toBe(125);
    expect(res.healthy).toBe(true);
  });
});
