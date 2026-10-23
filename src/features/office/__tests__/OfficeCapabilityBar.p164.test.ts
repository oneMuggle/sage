import { describe, expect, it } from 'vitest';

import {
  auditOfficeCapabilityBar,
  auditOfficeCapabilityBarGovernance,
  exportOfficeCapabilityBarAuditJson,
} from '../OfficeCapabilityBar';

describe('OfficeCapabilityBar governance audit (P164)', () => {
  it('returns ready governance status for OfficeCapabilityBar', () => {
    const snap = auditOfficeCapabilityBarGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/OfficeCapabilityBar.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('audits office capability bar report and json', () => {
    expect(auditOfficeCapabilityBar(4, true).capabilityCount).toBe(4);
    expect(JSON.parse(exportOfficeCapabilityBarAuditJson(2, false)).capabilityCount).toBe(2);
  });
});
