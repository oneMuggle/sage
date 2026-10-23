import { describe, expect, it } from 'vitest';

import {
  auditOfficeFeatureBarrel,
  auditOfficeFeatureBarrelGovernance,
  exportOfficeFeatureBarrelAuditJson,
} from '../index';

describe('office index barrel governance audit (P165)', () => {
  it('returns ready governance status for office/index.ts', () => {
    const snap = auditOfficeFeatureBarrelGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/index.ts',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('audits office feature barrel exports and json', () => {
    expect(auditOfficeFeatureBarrel().symbolCount).toBe(12);
    expect(JSON.parse(exportOfficeFeatureBarrelAuditJson()).symbolCount).toBe(12);
  });
});
