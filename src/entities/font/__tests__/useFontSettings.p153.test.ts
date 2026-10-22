import { describe, expect, it } from 'vitest';

import { auditUseFontSettingsGovernance } from '../useFontSettings';

describe('useFontSettings P153 governance audit', () => {
  it('returns healthy defaults for useFontSettings governance', () => {
    const res = auditUseFontSettingsGovernance();
    expect(res.module).toBe('src/entities/font/useFontSettings.tsx');
    expect(res.phase).toBe('P153');
    expect(res.ready).toBe(true);
    expect(res.uiSize).toBe(14);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when ready is false', () => {
    const res = auditUseFontSettingsGovernance({
      ready: false,
      uiSize: 30,
    });
    expect(res.ready).toBe(false);
    expect(res.uiSize).toBe(24);
    expect(res.healthy).toBe(false);
  });
});
