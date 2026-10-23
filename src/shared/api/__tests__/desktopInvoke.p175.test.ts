import { describe, expect, it } from 'vitest';

import { auditDesktopInvokeGovernance } from '../desktopInvoke';

describe('auditDesktopInvokeGovernance (P175)', () => {
  it('returns compliant governance audit metadata for desktopInvoke', () => {
    const report = auditDesktopInvokeGovernance();
    expect(report.module).toBe('src/shared/api/desktopInvoke.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.supportsReadinessGateAndConnectionNormalization).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
