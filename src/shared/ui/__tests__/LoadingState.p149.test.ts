import { describe, expect, it } from 'vitest';

import { auditLoadingStateGovernance } from '../LoadingState/LoadingState';

describe('LoadingState P149 governance audit', () => {
  it('returns healthy defaults for LoadingState governance', () => {
    const res = auditLoadingStateGovernance();
    expect(res.module).toBe('src/shared/ui/LoadingState/LoadingState.tsx');
    expect(res.phase).toBe('P149');
    expect(res.variant).toBe('spinner');
    expect(res.skeletonRows).toBe(3);
    expect(res.healthy).toBe(true);
  });

  it('normalizes variant and clamps skeletonRows', () => {
    const res = auditLoadingStateGovernance({
      variant: 'skeleton',
      skeletonRows: 50,
    });
    expect(res.variant).toBe('skeleton');
    expect(res.skeletonRows).toBe(20);
    expect(res.healthy).toBe(true);
  });
});
