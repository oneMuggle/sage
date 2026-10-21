import { describe, expect, it } from 'vitest';

import {
  formatCreateGoalModalJson,
  formatCreateGoalModalSummary,
} from '../CreateGoalModal';

describe('CreateGoalModal audit helpers', () => {
  it('formats create goal modal summary', () => {
    expect(formatCreateGoalModalSummary(true, 4, 500000)).toBe(
      'open=true · maxHours=4 · maxTokens=500000',
    );
    expect(formatCreateGoalModalSummary(false, -2, -10)).toBe(
      'open=false · maxHours=0 · maxTokens=0',
    );
  });

  it('exports create goal modal JSON snapshot', () => {
    expect(JSON.parse(formatCreateGoalModalJson(true, 2.5, 100000))).toEqual({
      isOpen: true,
      maxHours: 2.5,
      maxTokens: 100000,
    });
  });
});

