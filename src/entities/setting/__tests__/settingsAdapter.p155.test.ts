import { describe, expect, it } from 'vitest';

import { auditSettingsAdapterGovernance } from '../settingsAdapter';

describe('settingsAdapter P155 governance audit', () => {
  it('returns healthy defaults for settingsAdapter governance', () => {
    const res = auditSettingsAdapterGovernance();
    expect(res.module).toBe('src/entities/setting/settingsAdapter.ts');
    expect(res.phase).toBe('P155');
    expect(res.key).toBe('general.theme');
    expect(res.routeHealthy).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when routeHealthy is false', () => {
    const res = auditSettingsAdapterGovernance({
      key: 'custom.key',
      routeHealthy: false,
    });
    expect(res.key).toBe('custom.key');
    expect(res.routeHealthy).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
