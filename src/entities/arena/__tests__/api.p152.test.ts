import { describe, expect, it } from 'vitest';

import { auditArenaApiGovernance } from '../api';

describe('arena api P152 governance audit', () => {
  it('returns healthy defaults for arena api governance', () => {
    const res = auditArenaApiGovernance();
    expect(res.module).toBe('src/entities/arena/api.ts');
    expect(res.phase).toBe('P152');
    expect(res.activeAccountCount).toBe(1);
    expect(res.isolatedAccountCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes negative account counts to 0', () => {
    const res = auditArenaApiGovernance({
      activeAccountCount: -2,
      isolatedAccountCount: -1,
    });
    expect(res.activeAccountCount).toBe(0);
    expect(res.isolatedAccountCount).toBe(0);
    expect(res.healthy).toBe(true);
  });
});
