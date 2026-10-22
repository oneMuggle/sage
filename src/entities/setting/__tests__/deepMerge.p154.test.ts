import { describe, expect, it } from 'vitest';

import { auditDeepMergeGovernance } from '../deepMerge';

describe('deepMerge P154 governance audit', () => {
  it('returns healthy defaults for deepMerge governance', () => {
    const res = auditDeepMergeGovernance();
    expect(res.module).toBe('src/entities/setting/deepMerge.ts');
    expect(res.phase).toBe('P154');
    expect(res.maxDepth).toBe(16);
    expect(res.preserveUndefined).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('clamps maxDepth and normalizes preserveUndefined', () => {
    const res = auditDeepMergeGovernance({
      maxDepth: 100,
      preserveUndefined: true,
    });
    expect(res.maxDepth).toBe(32);
    expect(res.preserveUndefined).toBe(true);
    expect(res.healthy).toBe(true);
  });
});
