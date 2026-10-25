import { describe, expect, it } from 'vitest';

import { auditChatNoticeStackGovernance } from '../ChatNoticeStack';

describe('auditChatNoticeStackGovernance (Phase P193)', () => {
  it('returns deterministic P193 governance audit payload', () => {
    const payload = JSON.parse(auditChatNoticeStackGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('chat-notice-stack');
    expect(payload.phase).toBe('P193');
    expect(payload.audited).toBe(true);
  });
});
