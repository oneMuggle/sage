import { describe, expect, it } from 'vitest';

import {
  formatGoalDetailJson,
  formatGoalDetailSummary,
} from '../GoalDetailPage';

describe('GoalDetailPage audit helpers', () => {
  it('formats goal detail summary', () => {
    expect(formatGoalDetailSummary('running', 3)).toBe(
      'status=running · label=运行中 · checkpoints=3',
    );
    expect(formatGoalDetailSummary(null, -1)).toBe(
      'status=none · label=none · checkpoints=0',
    );
  });

  it('exports goal detail JSON snapshot', () => {
    expect(JSON.parse(formatGoalDetailJson('completed', 5))).toEqual({
      status: 'completed',
      label: '已完成',
      checkpointCount: 5,
    });
  });
});

