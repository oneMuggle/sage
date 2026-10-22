import { describe, expect, it } from 'vitest';

import { auditDialogBarrelGovernance } from '../Dialog/index';

describe('Dialog barrel P147 governance audit', () => {
  it('returns healthy defaults for Dialog barrel governance', () => {
    const res = auditDialogBarrelGovernance();
    expect(res.module).toBe('src/shared/ui/Dialog/index.ts');
    expect(res.phase).toBe('P147');
    expect(res.exportedPrimitiveCount).toBe(9);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when exportedPrimitiveCount is below threshold', () => {
    const res = auditDialogBarrelGovernance({
      exportedPrimitiveCount: 3,
    });
    expect(res.exportedPrimitiveCount).toBe(3);
    expect(res.healthy).toBe(false);
  });
});
