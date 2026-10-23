import { describe, expect, it } from 'vitest';

import {
  auditOfficeCapabilitiesGovernance,
  formatOfficeCapabilitiesJson,
  formatOfficeCapabilitiesSummary,
} from '../officeCapabilities';

describe('officeCapabilities governance audit (P165)', () => {
  it('returns ready governance status for officeCapabilities', () => {
    const snap = auditOfficeCapabilitiesGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/officeCapabilities.ts',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('formats office capabilities summary and json when null', () => {
    expect(formatOfficeCapabilitiesSummary(null)).toBe('unavailable');
    expect(JSON.parse(formatOfficeCapabilitiesJson(null))).toMatchObject({
      available: false,
      pdfFormats: [],
    });
  });
});
