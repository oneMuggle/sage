import { describe, expect, it } from 'vitest';

import { auditArtifactApiGovernance } from '../artifactApi';

describe('artifactApi P157 governance audit', () => {
  it('returns healthy defaults for artifactApi governance', () => {
    const res = auditArtifactApiGovernance();
    expect(res.module).toBe('src/features/artifacts/artifactApi.ts');
    expect(res.phase).toBe('P157');
    expect(res.artifactCount).toBe(1);
    expect(res.versionCount).toBe(1);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when versionCount is less than artifactCount', () => {
    const res = auditArtifactApiGovernance({
      artifactCount: 3,
      versionCount: 1,
    });
    expect(res.artifactCount).toBe(3);
    expect(res.versionCount).toBe(1);
    expect(res.healthy).toBe(false);
  });
});
