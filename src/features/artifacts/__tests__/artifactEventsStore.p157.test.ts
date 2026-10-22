import { describe, expect, it } from 'vitest';

import { auditArtifactEventsStoreGovernance } from '../artifactEventsStore';

describe('artifactEventsStore P157 governance audit', () => {
  it('returns healthy defaults for artifactEventsStore governance', () => {
    const res = auditArtifactEventsStoreGovernance();
    expect(res.module).toBe('src/features/artifacts/artifactEventsStore.ts');
    expect(res.phase).toBe('P157');
    expect(res.trackedSessionCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when trackedSessionCount exceeds 200', () => {
    const res = auditArtifactEventsStoreGovernance({ trackedSessionCount: 250 });
    expect(res.trackedSessionCount).toBe(250);
    expect(res.healthy).toBe(false);
  });
});
