import { describe, expect, it } from 'vitest';

import {
  evaluateTruncationNoticeAudit,
  exportTruncationNoticeAuditJson,
} from '../TruncationNotice';

describe('TruncationNotice audit diagnostics (Phase P135)', () => {
  it('computes omitted char count for expandable truncation notice', () => {
    const report = evaluateTruncationNoticeAudit({
      originalCharCount: 5000,
      displayedCharCount: 2000,
      canExpand: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.omittedCharCount).toBe(3000);
  });

  it('flags non-expandable truncated notice', () => {
    const parsed = JSON.parse(
      exportTruncationNoticeAuditJson({
        originalCharCount: 1000,
        displayedCharCount: 400,
        canExpand: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('truncated_content_not_expandable');
  });
});
