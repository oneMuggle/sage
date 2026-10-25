import { describe, expect, it } from 'vitest';

import { auditChatFindBarGovernance } from '../ChatFindBar';

describe('auditChatFindBarGovernance (Phase P193)', () => {
  it('returns deterministic P193 governance audit payload', () => {
    const payload = JSON.parse(auditChatFindBarGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('chat-find-bar');
    expect(payload.phase).toBe('P193');
    expect(payload.audited).toBe(true);
  });
});
