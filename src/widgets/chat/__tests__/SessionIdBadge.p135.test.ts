import { describe, expect, it } from 'vitest';

import {
  evaluateSessionIdBadgeAudit,
  exportSessionIdBadgeAuditJson,
} from '../SessionIdBadge';

describe('SessionIdBadge audit diagnostics (Phase P135)', () => {
  it('computes short label for valid session id', () => {
    const report = evaluateSessionIdBadgeAudit({
      sessionId: 'sess-1234567890',
      copiedRecently: false,
      displayPrefixLength: 9,
    });
    expect(report.healthy).toBe(true);
    expect(report.shortLabel).toBe('sess-1234');
  });

  it('flags missing or overly short session id', () => {
    const parsed = JSON.parse(
      exportSessionIdBadgeAuditJson({
        sessionId: 'abc',
        copiedRecently: true,
        displayPrefixLength: 8,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('session_id_too_short');
  });
});
