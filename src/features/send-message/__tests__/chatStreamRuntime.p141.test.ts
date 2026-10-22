import { describe, expect, it } from 'vitest';

import { evaluateChatStreamRuntimeGovernanceAudit } from '../chatStreamRuntime';

describe('evaluateChatStreamRuntimeGovernanceAudit (Phase P141)', () => {
  it('returns healthy report when active streams are within concurrency limit and abortable', () => {
    const report = evaluateChatStreamRuntimeGovernanceAudit({
      activeStreamCount: 2,
      maxConcurrentStreams: 8,
      pendingMessageCount: 1,
      hasAbortController: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.withinConcurrencyLimit).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags concurrency overflow and missing abort controller', () => {
    const report = evaluateChatStreamRuntimeGovernanceAudit({
      activeStreamCount: 10,
      maxConcurrentStreams: 4,
      pendingMessageCount: -1,
      hasAbortController: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'CHAT_STREAM_RUNTIME_COUNT_NEGATIVE',
      'CHAT_STREAM_RUNTIME_CONCURRENCY_EXCEEDED',
      'CHAT_STREAM_RUNTIME_ABORT_CONTROLLER_MISSING',
    ]);
  });
});
