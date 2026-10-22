import { describe, expect, it } from 'vitest';

import { auditArtifactListStoreGovernance } from '../artifactListStore';

describe('artifactListStore P157 governance audit', () => {
  it('returns healthy defaults for artifactListStore governance', () => {
    const res = auditArtifactListStoreGovernance();
    expect(res.module).toBe('src/features/artifacts/artifactListStore.ts');
    expect(res.phase).toBe('P157');
    expect(res.cachedSessionCount).toBe(0);
    expect(res.loadingCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when loadingCount exceeds 10', () => {
    const res = auditArtifactListStoreGovernance({
      cachedSessionCount: 3,
      loadingCount: 15,
    });
    expect(res.cachedSessionCount).toBe(3);
    expect(res.loadingCount).toBe(15);
    expect(res.healthy).toBe(false);
  });
});
