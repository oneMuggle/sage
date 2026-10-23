import { describe, expect, it } from 'vitest';

import { auditLoadingStateBarrelGovernance } from '../LoadingState/index';

describe('LoadingState barrel P147 governance audit', () => {
  it('returns healthy defaults for LoadingState barrel governance', () => {
    const res = auditLoadingStateBarrelGovernance();
    expect(res.module).toBe('src/shared/ui/LoadingState/index.ts');
    expect(res.phase).toBe('P147');
    expect(res.hasAccessibleLabel).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes hasAccessibleLabel', () => {
    const res = auditLoadingStateBarrelGovernance({
      hasAccessibleLabel: false,
    });
    expect(res.hasAccessibleLabel).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
