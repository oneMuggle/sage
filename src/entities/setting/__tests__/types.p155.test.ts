import { describe, expect, it } from 'vitest';

import {
  auditSettingTypesGovernance,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
} from '../types';

describe('setting types P155 governance audit', () => {
  it('returns healthy defaults for setting types governance', () => {
    const res = auditSettingTypesGovernance();
    expect(res.module).toBe('src/entities/setting/types.ts');
    expect(res.phase).toBe('P155');
    expect(res.version).toBe(SETTINGS_VERSION);
    expect(res.storageKey).toBe(SETTINGS_STORAGE_KEY);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when version or storageKey mismatches', () => {
    const res = auditSettingTypesGovernance({
      version: '1.0.0',
      storageKey: 'legacy',
    });
    expect(res.version).toBe('1.0.0');
    expect(res.storageKey).toBe('legacy');
    expect(res.healthy).toBe(false);
  });
});
