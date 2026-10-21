import { describe, expect, it } from 'vitest';

import {
  formatOfficeProgressJson,
  formatOfficeProgressSummary,
} from '../officeProgress';

describe('officeProgress audit helpers', () => {
  it('formats office progress tick summary', () => {
    expect(
      formatOfficeProgressSummary('task-7', { stage: 'rendering', percent: 65 }),
    ).toBe('task=task-7 · stage=rendering · percent=65%');
  });

  it('serializes office progress audit JSON', () => {
    expect(
      JSON.parse(
        formatOfficeProgressJson('task-8', { stage: 'exporting', percent: 90 }),
      ),
    ).toEqual({
      taskId: 'task-8',
      stage: 'exporting',
      percent: 90,
    });
  });
});
