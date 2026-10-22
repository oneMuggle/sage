import { describe, expect, it } from 'vitest';

import {
  auditThemePresetsGovernance,
  DEFAULT_THEME_ID,
  themePresets,
} from '../presets';

describe('theme presets P156 governance audit', () => {
  it('returns healthy defaults for theme presets governance', () => {
    const res = auditThemePresetsGovernance();
    expect(res.module).toBe('src/entities/theme/presets.ts');
    expect(res.phase).toBe('P156');
    expect(res.presetCount).toBe(themePresets.length);
    expect(res.defaultId).toBe(DEFAULT_THEME_ID);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when presetCount is 0', () => {
    const res = auditThemePresetsGovernance({ presetCount: 0 });
    expect(res.presetCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
