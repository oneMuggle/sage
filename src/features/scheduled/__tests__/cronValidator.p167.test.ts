import { describe, expect, it } from 'vitest';

import { auditCronValidatorGovernance } from '../cronValidator';

describe('auditCronValidatorGovernance (P167)', () => {
  it('returns compliant governance audit metadata for cronValidator', () => {
    const report = auditCronValidatorGovernance();
    expect(report.module).toBe('src/features/scheduled/cronValidator.ts');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('scheduled');
    expect(report.fieldCount).toBe(5);
    expect(report.zeroExternalDeps).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
