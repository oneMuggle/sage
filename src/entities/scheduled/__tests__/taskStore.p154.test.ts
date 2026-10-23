import { describe, expect, it } from 'vitest';

import { auditScheduledTaskStoreGovernance } from '../taskStore';

describe('scheduled taskStore P154 governance audit', () => {
  it('returns healthy defaults for scheduled taskStore governance', () => {
    const res = auditScheduledTaskStoreGovernance();
    expect(res.module).toBe('src/entities/scheduled/taskStore.ts');
    expect(res.phase).toBe('P154');
    expect(res.taskCount).toBe(0);
    expect(res.hasError).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasError is true', () => {
    const res = auditScheduledTaskStoreGovernance({
      taskCount: 5,
      hasError: true,
    });
    expect(res.taskCount).toBe(5);
    expect(res.hasError).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
