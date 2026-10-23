import { describe, expect, it } from 'vitest';

import { auditCronExpressionPickerGovernance } from '../CronExpressionPicker';

describe('auditCronExpressionPickerGovernance (P167)', () => {
  it('returns compliant governance audit metadata for CronExpressionPicker', () => {
    const report = auditCronExpressionPickerGovernance();
    expect(report.module).toBe('src/features/scheduled/CronExpressionPicker.tsx');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('scheduled');
    expect(report.supportsPresets).toBe(true);
    expect(report.supportsLiveValidation).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
