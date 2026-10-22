import { describe, expect, it } from 'vitest';

import { auditChatApiGovernance } from '../chatApi';

describe('chatApi P144 governance audit', () => {
  it('returns healthy defaults for chatApi governance', () => {
    const res = auditChatApiGovernance();
    expect(res.module).toBe('src/shared/api/chatApi.ts');
    expect(res.phase).toBe('P144');
    expect(res.activeStreamCount).toBe(0);
    expect(res.maxConcurrentStreams).toBe(4);
    expect(res.supportsSseResume).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes stream counts and flags overflow', () => {
    const res = auditChatApiGovernance({
      activeStreamCount: 6.9,
      maxConcurrentStreams: 4,
      supportsSseResume: true,
    });
    expect(res.activeStreamCount).toBe(6);
    expect(res.maxConcurrentStreams).toBe(4);
    expect(res.healthy).toBe(false);
  });
});
