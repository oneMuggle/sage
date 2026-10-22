import { describe, expect, it } from 'vitest';

import { auditThemeStorageGovernance } from '../storage';

describe('theme storage P156 governance audit', () => {
  it('returns healthy defaults for theme storage governance', () => {
    const res = auditThemeStorageGovernance();
    expect(res.module).toBe('src/entities/theme/storage.ts');
    expect(res.phase).toBe('P156');
    expect(res.mode).toBe('system');
    expect(res.presetId).toBe('indigo');
    expect(res.healthy).toBe(true);
  });

  it('normalizes mode and presetId', () => {
    const res = auditThemeStorageGovernance({
      mode: 'dark',
      presetId: 'emerald',
    });
    expect(res.mode).toBe('dark');
    expect(res.presetId).toBe('emerald');
    expect(res.healthy).toBe(true);
  });
});
