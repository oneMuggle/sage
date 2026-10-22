import { describe, expect, it } from 'vitest';

import {
  evaluateTopicSeparatorAudit,
  exportTopicSeparatorAuditJson,
} from '../TopicSeparator';

describe('TopicSeparator audit diagnostics (Phase P135)', () => {
  it('validates topic separator with title and timestamp', () => {
    const report = evaluateTopicSeparatorAudit({
      topicTitle: 'Database Migration',
      timestampMs: 1729584000000,
      messageCountBefore: 12,
    });
    expect(report.healthy).toBe(true);
    expect(report.hasValidTimestamp).toBe(true);
  });

  it('flags empty title and invalid timestamp', () => {
    const parsed = JSON.parse(
      exportTopicSeparatorAuditJson({
        topicTitle: ' ',
        timestampMs: 0,
        messageCountBefore: 0,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('empty_topic_separator_title');
    expect(parsed.issueCodes).toContain('invalid_topic_separator_timestamp');
  });
});
