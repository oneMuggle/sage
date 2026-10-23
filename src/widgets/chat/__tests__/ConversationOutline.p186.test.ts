import { describe, expect, it } from 'vitest';

import { auditConversationOutlineGovernance } from '../ConversationOutline';

describe('auditConversationOutlineGovernance (Phase P186)', () => {
  it('returns deterministic P186 governance audit payload', () => {
    const payload = JSON.parse(auditConversationOutlineGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('conversation-outline');
    expect(payload.phase).toBe('P186');
    expect(payload.audited).toBe(true);
  });
});
