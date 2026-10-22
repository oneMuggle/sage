import { describe, expect, it } from 'vitest';

import { auditUseArtifactsGovernance } from '../useArtifacts';

describe('useArtifacts P158 governance audit', () => {
  it('returns healthy defaults for useArtifacts governance', () => {
    const res = auditUseArtifactsGovernance();
    expect(res.module).toBe('src/features/artifacts/useArtifacts.ts');
    expect(res.phase).toBe('P158');
    expect(res.artifactCount).toBe(0);
    expect(res.hasError).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasError is true', () => {
    const res = auditUseArtifactsGovernance({
      artifactCount: 3,
      hasError: true,
    });
    expect(res.artifactCount).toBe(3);
    expect(res.hasError).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
