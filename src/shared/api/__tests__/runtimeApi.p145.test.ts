import { describe, expect, it } from 'vitest';

import { auditRuntimeApiGovernance } from '../runtimeApi';

describe('runtimeApi P145 governance audit', () => {
  it('returns healthy defaults for runtimeApi governance', () => {
    const res = auditRuntimeApiGovernance();
    expect(res.module).toBe('src/shared/api/runtimeApi.ts');
    expect(res.phase).toBe('P145');
    expect(res.backendConnected).toBe(true);
    expect(res.activeProfile).toBe('default');
    expect(res.healthy).toBe(true);
  });

  it('normalizes activeProfile and backendConnected flag', () => {
    const res = auditRuntimeApiGovernance({
      backendConnected: false,
      activeProfile: ' win7-lts ',
    });
    expect(res.backendConnected).toBe(false);
    expect(res.activeProfile).toBe('win7-lts');
    expect(res.healthy).toBe(false);
  });
});
