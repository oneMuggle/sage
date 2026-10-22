import { describe, expect, it } from 'vitest';

import { auditSettingsBarrelGovernance } from '../index';

describe('settings barrel P148 governance audit', () => {
  it('returns healthy defaults for settings barrel governance', () => {
    const res = auditSettingsBarrelGovernance();
    expect(res.module).toBe('src/pages/settings/index.ts');
    expect(res.phase).toBe('P148');
    expect(res.tabCount).toBe(8);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when tabCount is 0', () => {
    const res = auditSettingsBarrelGovernance({ tabCount: 0 });
    expect(res.tabCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
