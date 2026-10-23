import { describe, expect, it } from 'vitest';

import { auditTransparencyPayloadGovernance } from '../transparencyPayload';

describe('auditTransparencyPayloadGovernance (P168)', () => {
  it('returns compliant governance audit metadata for transparencyPayload', () => {
    const report = auditTransparencyPayloadGovernance();
    expect(report.module).toBe('src/features/send-message/transparencyPayload.ts');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('send-message');
    expect(report.validatesContextPressureAndCompact).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
