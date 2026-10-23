import { describe, expect, it } from 'vitest';

import { auditQuestionStateGovernance } from '../questionState';

describe('questionState P154 governance audit', () => {
  it('returns healthy defaults for questionState governance', () => {
    const res = auditQuestionStateGovernance();
    expect(res.module).toBe('src/entities/question/questionState.ts');
    expect(res.phase).toBe('P154');
    expect(res.pendingCount).toBe(0);
    expect(res.maxQueueDepth).toBe(50);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when pendingCount exceeds maxQueueDepth', () => {
    const res = auditQuestionStateGovernance({
      pendingCount: 75,
      maxQueueDepth: 50,
    });
    expect(res.pendingCount).toBe(75);
    expect(res.maxQueueDepth).toBe(50);
    expect(res.healthy).toBe(false);
  });
});
