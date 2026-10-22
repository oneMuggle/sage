import { describe, expect, it } from 'vitest';

import { auditVisionContentGovernance, PHILOSOPHY } from '../vision';

describe('vision content P152 governance audit', () => {
  it('returns healthy defaults for vision content governance', () => {
    const res = auditVisionContentGovernance();
    expect(res.module).toBe('src/content/about/vision.ts');
    expect(res.phase).toBe('P152');
    expect(res.pillarCount).toBe(PHILOSOPHY.length);
    expect(res.hasVisionStatement).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when pillarCount is 0 or hasVisionStatement is false', () => {
    const res = auditVisionContentGovernance({
      pillarCount: 0,
      hasVisionStatement: false,
    });
    expect(res.pillarCount).toBe(0);
    expect(res.hasVisionStatement).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
