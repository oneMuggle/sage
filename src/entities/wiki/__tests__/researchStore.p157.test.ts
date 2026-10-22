import { describe, expect, it } from 'vitest';

import { auditWikiResearchStoreGovernance } from '../research-store';

describe('wiki research-store P157 governance audit', () => {
  it('returns healthy defaults for wiki research-store governance', () => {
    const res = auditWikiResearchStoreGovernance();
    expect(res.module).toBe('src/entities/wiki/research-store.ts');
    expect(res.phase).toBe('P157');
    expect(res.taskCount).toBe(0);
    expect(res.runningCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when runningCount exceeds taskCount + 1', () => {
    const res = auditWikiResearchStoreGovernance({
      taskCount: 1,
      runningCount: 4,
    });
    expect(res.taskCount).toBe(1);
    expect(res.runningCount).toBe(4);
    expect(res.healthy).toBe(false);
  });
});
