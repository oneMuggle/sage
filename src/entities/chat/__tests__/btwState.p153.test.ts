import { describe, expect, it } from 'vitest';

import { auditBtwStateGovernance } from '../btwState';

describe('btwState P153 governance audit', () => {
  it('returns healthy defaults for btwState governance', () => {
    const res = auditBtwStateGovernance();
    expect(res.module).toBe('src/entities/chat/btwState.ts');
    expect(res.phase).toBe('P153');
    expect(res.isOpen).toBe(false);
    expect(res.messageCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when messageCount exceeds 500', () => {
    const res = auditBtwStateGovernance({
      isOpen: true,
      messageCount: 600,
    });
    expect(res.isOpen).toBe(true);
    expect(res.messageCount).toBe(600);
    expect(res.healthy).toBe(false);
  });
});
