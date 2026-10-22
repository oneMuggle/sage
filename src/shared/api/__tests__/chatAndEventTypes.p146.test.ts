import { describe, expect, it } from 'vitest';

import { auditChatAndEventTypesGovernance } from '../types/chatAndEventTypes';

describe('chatAndEventTypes P146 governance audit', () => {
  it('returns healthy defaults for chatAndEventTypes governance', () => {
    const res = auditChatAndEventTypesGovernance();
    expect(res.module).toBe('src/shared/api/types/chatAndEventTypes.ts');
    expect(res.phase).toBe('P146');
    expect(res.taskStatus).toBe('done');
    expect(res.todoStatus).toBe('completed');
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when taskStatus is failed', () => {
    const res = auditChatAndEventTypesGovernance({
      taskStatus: 'failed',
      todoStatus: 'in_progress',
    });
    expect(res.taskStatus).toBe('failed');
    expect(res.todoStatus).toBe('in_progress');
    expect(res.healthy).toBe(false);
  });
});
