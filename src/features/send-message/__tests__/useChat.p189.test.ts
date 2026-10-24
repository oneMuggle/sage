import { describe, expect, it } from 'vitest';

import { auditSendMessageUseChatGovernance } from '../useChat';

describe('auditSendMessageUseChatGovernance (Phase P189)', () => {
  it('returns deterministic P189 governance audit payload', () => {
    const payload = JSON.parse(auditSendMessageUseChatGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('send-message-use-chat');
    expect(payload.phase).toBe('P189');
    expect(payload.audited).toBe(true);
  });
});
