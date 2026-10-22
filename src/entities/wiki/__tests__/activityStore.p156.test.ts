import { describe, expect, it } from 'vitest';

import { auditWikiActivityStoreGovernance } from '../activity-store';

describe('wiki activity-store P156 governance audit', () => {
  it('returns healthy defaults for wiki activity-store governance', () => {
    const res = auditWikiActivityStoreGovernance();
    expect(res.module).toBe('src/entities/wiki/activity-store.ts');
    expect(res.phase).toBe('P156');
    expect(res.activityCount).toBe(0);
    expect(res.maxRetained).toBe(200);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when activityCount exceeds maxRetained', () => {
    const res = auditWikiActivityStoreGovernance({
      activityCount: 250,
      maxRetained: 200,
    });
    expect(res.activityCount).toBe(250);
    expect(res.maxRetained).toBe(200);
    expect(res.healthy).toBe(false);
  });
});
