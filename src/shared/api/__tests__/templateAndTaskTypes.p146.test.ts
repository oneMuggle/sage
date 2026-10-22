import { describe, expect, it } from 'vitest';

import { auditTemplateAndTaskTypesGovernance } from '../types/templateAndTaskTypes';

describe('templateAndTaskTypes P146 governance audit', () => {
  it('returns healthy defaults for templateAndTaskTypes governance', () => {
    const res = auditTemplateAndTaskTypesGovernance();
    expect(res.module).toBe('src/shared/api/types/templateAndTaskTypes.ts');
    expect(res.phase).toBe('P146');
    expect(res.todoPriority).toBe('medium');
    expect(res.todoStatus).toBe('completed');
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when todoStatus is cancelled', () => {
    const res = auditTemplateAndTaskTypesGovernance({
      todoPriority: 'high',
      todoStatus: 'cancelled',
    });
    expect(res.todoPriority).toBe('high');
    expect(res.todoStatus).toBe('cancelled');
    expect(res.healthy).toBe(false);
  });
});
