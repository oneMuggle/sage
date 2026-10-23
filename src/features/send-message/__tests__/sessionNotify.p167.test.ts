import { describe, expect, it } from 'vitest';

import { auditSessionNotifyGovernance } from '../sessionNotify';

describe('auditSessionNotifyGovernance (P167)', () => {
  it('returns compliant governance audit metadata for sessionNotify', () => {
    const report = auditSessionNotifyGovernance();
    expect(report.module).toBe('src/features/send-message/sessionNotify.ts');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('send-message');
    expect(report.suppressesActiveVisibleSession).toBe(true);
    expect(report.suppressesBtwPseudoSession).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
