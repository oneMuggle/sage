import { describe, expect, it } from 'vitest';

import { auditWikiQueueStoreGovernance } from '../queue-store';

describe('wiki queue-store P156 governance audit', () => {
  it('returns healthy defaults for wiki queue-store governance', () => {
    const res = auditWikiQueueStoreGovernance();
    expect(res.module).toBe('src/entities/wiki/queue-store.ts');
    expect(res.phase).toBe('P156');
    expect(res.pendingCount).toBe(0);
    expect(res.failedCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when failedCount is greater than 0', () => {
    const res = auditWikiQueueStoreGovernance({
      pendingCount: 2,
      failedCount: 1,
    });
    expect(res.pendingCount).toBe(2);
    expect(res.failedCount).toBe(1);
    expect(res.healthy).toBe(false);
  });
});
