import { describe, expect, it } from 'vitest';

import { auditWorktreeApiGovernance } from '../worktreeApi';

describe('worktreeApi P146 governance audit', () => {
  it('returns healthy defaults for worktreeApi governance', () => {
    const res = auditWorktreeApiGovernance();
    expect(res.module).toBe('src/shared/api/worktreeApi.ts');
    expect(res.phase).toBe('P146');
    expect(res.mode).toBe('new');
    expect(res.worktreeCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes mode and worktreeCount', () => {
    const res = auditWorktreeApiGovernance({
      mode: 'checkout',
      worktreeCount: 4.7,
    });
    expect(res.mode).toBe('checkout');
    expect(res.worktreeCount).toBe(4);
    expect(res.healthy).toBe(true);
  });
});
