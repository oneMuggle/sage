import { describe, expect, it } from 'vitest';

import { auditSharedUiBarrelGovernance } from '../index';

describe('shared/ui barrel P146 governance audit', () => {
  it('returns healthy defaults for shared/ui barrel governance', () => {
    const res = auditSharedUiBarrelGovernance();
    expect(res.module).toBe('src/shared/ui/index.ts');
    expect(res.phase).toBe('P146');
    expect(res.exportedComponentCount).toBe(12);
    expect(res.healthy).toBe(true);
  });

  it('normalizes exportedComponentCount', () => {
    const res = auditSharedUiBarrelGovernance({
      exportedComponentCount: 4,
    });
    expect(res.exportedComponentCount).toBe(4);
    expect(res.healthy).toBe(false);
  });
});
