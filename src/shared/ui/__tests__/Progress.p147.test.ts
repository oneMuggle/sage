import { describe, expect, it } from 'vitest';

import { auditProgressGovernance } from '../Progress';

describe('Progress P147 governance audit', () => {
  it('returns healthy defaults for Progress governance', () => {
    const res = auditProgressGovernance();
    expect(res.module).toBe('src/shared/ui/Progress.tsx');
    expect(res.phase).toBe('P147');
    expect(res.clampedValue).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('clamps progress value between 0 and 100', () => {
    expect(auditProgressGovernance({ value: 145 }).clampedValue).toBe(100);
    expect(auditProgressGovernance({ value: -12 }).clampedValue).toBe(0);
  });
});
