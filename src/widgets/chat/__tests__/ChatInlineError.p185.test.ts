import { describe, expect, it } from 'vitest';

import { auditChatInlineErrorGovernance } from '../ChatInlineError';

describe('auditChatInlineErrorGovernance (Phase P185)', () => {
  it('returns deterministic P185 governance audit payload', () => {
    const payload = JSON.parse(auditChatInlineErrorGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('chat-inline-error');
    expect(payload.phase).toBe('P185');
    expect(payload.audited).toBe(true);
  });
});
