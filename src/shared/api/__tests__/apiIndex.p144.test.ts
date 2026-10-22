import { describe, expect, it } from 'vitest';

import { auditSharedApiBarrelGovernance } from '../index';

describe('shared/api/index P144 governance audit', () => {
  it('returns healthy defaults for shared API barrel governance', () => {
    const res = auditSharedApiBarrelGovernance();
    expect(res.module).toBe('src/shared/api/index.ts');
    expect(res.phase).toBe('P144');
    expect(res.exportedClientCount).toBe(12);
    expect(res.windowControlsReady).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes exportedClientCount and windowControlsReady', () => {
    const res = auditSharedApiBarrelGovernance({
      exportedClientCount: 0,
      windowControlsReady: false,
    });
    expect(res.exportedClientCount).toBe(0);
    expect(res.windowControlsReady).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
