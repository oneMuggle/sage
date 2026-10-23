import { describe, expect, it } from 'vitest';

import { auditChatStreamStoreGovernance } from '../chatStreamStore';

describe('auditChatStreamStoreGovernance (P167)', () => {
  it('returns compliant governance audit metadata for chatStreamStore', () => {
    const report = auditChatStreamStoreGovernance();
    expect(report.module).toBe('src/features/send-message/chatStreamStore.ts');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('send-message');
    expect(report.sessionScopedIsolation).toBe(true);
    expect(report.supportsTopicShiftAndTaskBoard).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
