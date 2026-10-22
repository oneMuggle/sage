import { describe, expect, it } from 'vitest';

import { auditUseAttentionSnapshotGovernance } from '../useAttentionSnapshot';

describe('useAttentionSnapshot P158 governance audit', () => {
  it('returns healthy defaults for useAttentionSnapshot governance', () => {
    const res = auditUseAttentionSnapshotGovernance();
    expect(res.module).toBe('src/features/attention/useAttentionSnapshot.ts');
    expect(res.phase).toBe('P158');
    expect(res.pendingTodoCount).toBe(0);
    expect(res.dirtyFileCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when dirtyFileCount exceeds 500', () => {
    const res = auditUseAttentionSnapshotGovernance({
      pendingTodoCount: 3,
      dirtyFileCount: 600,
    });
    expect(res.pendingTodoCount).toBe(3);
    expect(res.dirtyFileCount).toBe(600);
    expect(res.healthy).toBe(false);
  });
});
