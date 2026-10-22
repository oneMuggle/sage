import { describe, expect, it } from 'vitest';

import { auditAttentionBarrelGovernance } from '../index';

describe('attention barrel P158 governance audit', () => {
  it('returns healthy defaults for attention barrel governance', () => {
    const res = auditAttentionBarrelGovernance();
    expect(res.module).toBe('src/features/attention/index.ts');
    expect(res.phase).toBe('P158');
    expect(res.exportedCount).toBe(8);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when exportedCount drops below 5', () => {
    const res = auditAttentionBarrelGovernance({ exportedCount: 2 });
    expect(res.exportedCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
