import { describe, expect, it } from 'vitest';

import { auditModelCatalogTypesGovernance, REVIEWABLE_FIELDS } from '../types';

describe('model-catalog types P153 governance audit', () => {
  it('returns healthy defaults for model-catalog types governance', () => {
    const res = auditModelCatalogTypesGovernance();
    expect(res.module).toBe('src/entities/model-catalog/types.ts');
    expect(res.phase).toBe('P153');
    expect(res.reviewableFieldCount).toBe(REVIEWABLE_FIELDS.length);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when reviewableFieldCount mismatches whitelist length', () => {
    const res = auditModelCatalogTypesGovernance({ reviewableFieldCount: 1 });
    expect(res.reviewableFieldCount).toBe(1);
    expect(res.healthy).toBe(false);
  });
});
