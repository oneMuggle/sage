import { describe, expect, it } from 'vitest';

import { auditPageSkeletonGovernance } from '../PageSkeleton/PageSkeleton';

describe('PageSkeleton P147 governance audit', () => {
  it('returns healthy defaults for PageSkeleton governance', () => {
    const res = auditPageSkeletonGovernance();
    expect(res.module).toBe('src/shared/ui/PageSkeleton/PageSkeleton.tsx');
    expect(res.phase).toBe('P147');
    expect(res.blockCount).toBe(4);
    expect(res.healthy).toBe(true);
  });

  it('clamps blockCount between 1 and 12', () => {
    expect(auditPageSkeletonGovernance({ blockCount: 25 }).blockCount).toBe(12);
    expect(auditPageSkeletonGovernance({ blockCount: 0 }).blockCount).toBe(1);
  });
});
