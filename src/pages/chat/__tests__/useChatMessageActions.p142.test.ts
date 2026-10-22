import { describe, expect, it } from 'vitest';

import { auditUseChatMessageActionsGovernance } from '../useChatMessageActions';

describe('useChatMessageActions P142 governance audit', () => {
  it('returns healthy defaults for chat message actions hook governance', () => {
    const res = auditUseChatMessageActionsGovernance();
    expect(res.module).toBe('src/pages/chat/useChatMessageActions.ts');
    expect(res.phase).toBe('P142');
    expect(res.messageCount).toBe(0);
    expect(res.isBusy).toBe(false);
    expect(res.supportsRegenerate).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes messageCount and busy state', () => {
    const res = auditUseChatMessageActionsGovernance({
      messageCount: 12.9,
      isBusy: true,
      supportsRegenerate: false,
    });
    expect(res.messageCount).toBe(12);
    expect(res.isBusy).toBe(true);
    expect(res.supportsRegenerate).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
