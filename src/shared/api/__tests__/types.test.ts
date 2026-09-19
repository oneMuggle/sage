import { describe, expect, it } from 'vitest';

import type { TaskPlanItem } from '../types';

describe('TaskPlanItem', () => {
  it('supports optional parent_task_id and depth', () => {
    const item: TaskPlanItem = {
      task_id: 't1',
      agent_id: 'researcher',
      goal: 'test',
      parent_task_id: null,
      depth: 0,
    };

    expect(item.parent_task_id).toBeNull();
    expect(item.depth).toBe(0);
  });

  it('allows omitting parent_task_id and depth for backward compatibility', () => {
    const item: TaskPlanItem = {
      task_id: 't1',
      agent_id: 'researcher',
      goal: 'test',
    };

    expect(item.parent_task_id).toBeUndefined();
    expect(item.depth).toBeUndefined();
  });
});
