import { describe, expect, it } from 'vitest';

import { auditUseArtifactContentGovernance } from '../useArtifactContent';

describe('useArtifactContent P158 governance audit', () => {
  it('returns healthy defaults for useArtifactContent governance', () => {
    const res = auditUseArtifactContentGovernance();
    expect(res.module).toBe('src/features/artifacts/useArtifactContent.ts');
    expect(res.phase).toBe('P158');
    expect(res.sessionId).toBe('default');
    expect(res.hasError).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasError is true', () => {
    const res = auditUseArtifactContentGovernance({
      sessionId: 'sess-1',
      hasError: true,
    });
    expect(res.sessionId).toBe('sess-1');
    expect(res.hasError).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
