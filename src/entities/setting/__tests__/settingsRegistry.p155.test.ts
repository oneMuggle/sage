import { describe, expect, it } from 'vitest';

import { auditSettingsRegistryGovernance, getAllSettingKeys } from '../settingsRegistry';

describe('settingsRegistry P155 governance audit', () => {
  it('returns healthy defaults for settingsRegistry governance', () => {
    const res = auditSettingsRegistryGovernance();
    expect(res.module).toBe('src/entities/setting/settingsRegistry.ts');
    expect(res.phase).toBe('P155');
    expect(res.registeredKeyCount).toBe(getAllSettingKeys().length);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when registeredKeyCount is below 5', () => {
    const res = auditSettingsRegistryGovernance({ registeredKeyCount: 2 });
    expect(res.registeredKeyCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
