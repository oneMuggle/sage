import { describe, expect, it } from 'vitest';

import { auditSettingMetadataGovernance } from '../metadata';

describe('setting metadata P155 governance audit', () => {
  it('returns healthy defaults for setting metadata governance', () => {
    const res = auditSettingMetadataGovernance();
    expect(res.module).toBe('src/entities/setting/metadata.ts');
    expect(res.phase).toBe('P155');
    expect(res.scope).toBe('global');
    expect(res.riskLevel).toBe('low');
    expect(res.healthy).toBe(true);
  });

  it('normalizes scope and riskLevel', () => {
    const res = auditSettingMetadataGovernance({
      scope: 'session',
      riskLevel: 'high',
    });
    expect(res.scope).toBe('session');
    expect(res.riskLevel).toBe('high');
    expect(res.healthy).toBe(true);
  });
});
