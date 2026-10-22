import { describe, expect, it } from 'vitest';

import { auditTodoStoreGovernance } from '../todoStore';

describe('todoStore P156 governance audit', () => {
  it('returns healthy defaults for todoStore governance', () => {
    const res = auditTodoStoreGovernance();
    expect(res.module).toBe('src/entities/todo/todoStore.ts');
    expect(res.phase).toBe('P156');
    expect(res.totalCount).toBe(0);
    expect(res.inProgressCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when inProgressCount exceeds 1', () => {
    const res = auditTodoStoreGovernance({
      totalCount: 4,
      inProgressCount: 2,
    });
    expect(res.totalCount).toBe(4);
    expect(res.inProgressCount).toBe(2);
    expect(res.healthy).toBe(false);
  });
});
