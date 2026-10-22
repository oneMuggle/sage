import { describe, expect, it } from 'vitest';

import {
  auditDecorativePresetsGovernance,
  decorativePresets,
} from '../decorative-presets';

describe('decorative-presets P155 governance audit', () => {
  it('returns healthy defaults for decorative-presets governance', () => {
    const res = auditDecorativePresetsGovernance();
    expect(res.module).toBe('src/entities/theme/decorative-presets.ts');
    expect(res.phase).toBe('P155');
    expect(res.presetCount).toBe(decorativePresets.length);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when presetCount is 0', () => {
    const res = auditDecorativePresetsGovernance({ presetCount: 0 });
    expect(res.presetCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
