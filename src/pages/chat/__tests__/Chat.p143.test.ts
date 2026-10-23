import { describe, expect, it } from 'vitest';

import { auditChatPageGovernance } from '../../Chat';

describe('Chat P143 governance audit', () => {
  it('returns healthy defaults for Chat page governance', () => {
    const res = auditChatPageGovernance();
    expect(res.module).toBe('src/pages/Chat.tsx');
    expect(res.phase).toBe('P143');
    expect(res.headerControlsInTopBar).toBe(true);
    expect(res.singleRowBottomComposer).toBe(true);
    expect(res.activeSessionId).toBe('default');
    expect(res.healthy).toBe(true);
  });

  it('normalizes activeSessionId and layout flags', () => {
    const res = auditChatPageGovernance({
      headerControlsInTopBar: true,
      singleRowBottomComposer: false,
      activeSessionId: ' sess-42 ',
    });
    expect(res.activeSessionId).toBe('sess-42');
    expect(res.singleRowBottomComposer).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
