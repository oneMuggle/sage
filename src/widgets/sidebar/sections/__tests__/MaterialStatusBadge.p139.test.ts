import { describe, expect, it } from 'vitest';

import { evaluateMaterialStatusBadgeGovernanceAudit } from '../MaterialStatusBadge';

describe('evaluateMaterialStatusBadgeGovernanceAudit (Phase P139)', () => {
  it('returns healthy report for recognized material status with label and title', () => {
    const report = evaluateMaterialStatusBadgeGovernanceAudit({
      status: 'indexed',
      hasLabelText: true,
      hasAccessibleTitle: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.recognizedStatus).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags unrecognized status and missing label/title attributes', () => {
    const report = evaluateMaterialStatusBadgeGovernanceAudit({
      status: 'corrupted_unknown',
      hasLabelText: false,
      hasAccessibleTitle: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'MATERIAL_STATUS_UNRECOGNIZED',
      'MATERIAL_STATUS_LABEL_MISSING',
      'MATERIAL_STATUS_TITLE_MISSING',
    ]);
  });
});
