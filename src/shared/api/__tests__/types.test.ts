import { describe, expect, it } from 'vitest';

import type { TaskPlanItem as StreamTaskPlanItem } from '../llmStream';
import type { TaskPlanItem } from '../types';
import { formatTaskPlanItemJson, formatTaskPlanItemSummary } from '../types';

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

  it('supports hierarchy fields in the streaming TaskPlanItem type', () => {
    const item: StreamTaskPlanItem = {
      task_id: 't1',
      agent_id: 'researcher',
      goal: 'test',
      parent_task_id: 'root',
      depth: 1,
    };

    expect(item.parent_task_id).toBe('root');
    expect(item.depth).toBe(1);
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

  it('formats TaskPlanItem summary and JSON (Phase P119)', () => {
    const item: TaskPlanItem = {
      task_id: 't2',
      agent_id: 'coder',
      goal: 'implement feature',
      parent_task_id: 't1',
      depth: 1,
    };
    expect(formatTaskPlanItemSummary(item)).toBe('t2 · agent=coder · parent=t1 · depth=1');
    expect(JSON.parse(formatTaskPlanItemJson(item))).toEqual({
      taskId: 't2',
      agentId: 'coder',
      goal: 'implement feature',
      parentTaskId: 't1',
      depth: 1,
    });
  });
});
