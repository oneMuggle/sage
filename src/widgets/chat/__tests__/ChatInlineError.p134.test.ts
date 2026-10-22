import { describe, expect, it } from 'vitest';

import {
  evaluateChatInlineErrorAudit,
  exportChatInlineErrorAuditJson,
} from '../ChatInlineError';

describe('ChatInlineError audit diagnostics (Phase P134)', () => {
  it('validates actionable retryable inline error', () => {
    const report = evaluateChatInlineErrorAudit({
      errorMessage: 'Network timeout',
      errorCode: 'NET_TIMEOUT',
      retryable: true,
      hasRetryHandler: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedCode).toBe('NET_TIMEOUT');
    expect(report.actionable).toBe(true);
  });

  it('flags missing message and retry handler', () => {
    const parsed = JSON.parse(
      exportChatInlineErrorAuditJson({
        errorMessage: '   ',
        errorCode: null,
        retryable: true,
        hasRetryHandler: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('empty_inline_error_message');
    expect(parsed.issueCodes).toContain('missing_retry_handler');
  });
});
