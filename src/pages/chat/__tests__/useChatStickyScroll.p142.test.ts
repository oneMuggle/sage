import { describe, expect, it } from 'vitest';

import { auditUseChatStickyScrollGovernance } from '../useChatStickyScroll';

describe('useChatStickyScroll P142 governance audit', () => {
  it('returns healthy defaults for chat sticky scroll hook governance', () => {
    const res = auditUseChatStickyScrollGovernance();
    expect(res.module).toBe('src/pages/chat/useChatStickyScroll.ts');
    expect(res.phase).toBe('P142');
    expect(res.stickToBottom).toBe(true);
    expect(res.scrollThresholdPx).toBe(80);
    expect(res.isStreaming).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('normalizes scrollThresholdPx and streaming flags', () => {
    const res = auditUseChatStickyScrollGovernance({
      stickToBottom: false,
      scrollThresholdPx: -15,
      isStreaming: true,
    });
    expect(res.stickToBottom).toBe(false);
    expect(res.scrollThresholdPx).toBe(0);
    expect(res.isStreaming).toBe(true);
    expect(res.healthy).toBe(true);
  });
});
