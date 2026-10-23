import { describe, expect, it } from 'vitest';

import { auditModelCatalogApiGovernance } from '../api';

describe('model-catalog api P153 governance audit', () => {
  it('returns healthy defaults for model-catalog api governance', () => {
    const res = auditModelCatalogApiGovernance();
    expect(res.module).toBe('src/entities/model-catalog/api.ts');
    expect(res.phase).toBe('P153');
    expect(res.modelCount).toBe(10);
    expect(res.snapshotCount).toBe(1);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when modelCount is 0', () => {
    const res = auditModelCatalogApiGovernance({
      modelCount: 0,
      snapshotCount: 0,
    });
    expect(res.modelCount).toBe(0);
    expect(res.snapshotCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
