import { describe, expect, it } from 'vitest';

import {
  formatGoalListFilterJson,
  formatGoalListFilterSummary,
} from '../GoalListPage';

describe('GoalListPage audit helpers', () => {
  it('formats goal list filter summary', () => {
    expect(formatGoalListFilterSummary(null, 4)).toBe(
      'filter=all · goals=4 · options=7',
    );
    expect(formatGoalListFilterSummary('running', -1)).toBe(
      'filter=running · goals=0 · options=7',
    );
  });

  it('exports goal list filter JSON snapshot', () => {
    expect(JSON.parse(formatGoalListFilterJson('pending', 2))).toEqual({
      filter: 'pending',
      goalCount: 2,
      optionCount: 7,
    });
  });
});

