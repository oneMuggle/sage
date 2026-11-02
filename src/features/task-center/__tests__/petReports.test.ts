import { describe, expect, it } from 'vitest';

import { toPetTaskReports } from '../petReports';
import type { TaskCenterEntry } from '../taskCenterStore';

function entry(overrides: Partial<TaskCenterEntry>): TaskCenterEntry {
  return {
    id: 't1',
    kind: 'office',
    title: '生成周报',
    startedAt: 1000,
    status: 'running',
    ...overrides,
  };
}

describe('toPetTaskReports', () => {
  it('omits succeeded/cancelled and keeps active/failed tasks', () => {
    const reports = toPetTaskReports({
      a: entry({ id: 'a', status: 'running' }),
      b: entry({ id: 'b', status: 'succeeded' }),
      c: entry({ id: 'c', status: 'failed', error: 'boom', finishedAt: 2000, startedAt: 2000 }),
      d: entry({ id: 'd', status: 'cancelled' }),
    });
    expect(reports.map((report) => report.id)).toEqual(['c', 'a']);
    expect(reports[0]).toMatchObject({ status: 'failed', error: 'boom', finishedAt: 2000 });
  });

  it('sorts by startedAt descending and caps the list', () => {
    const tasks: Record<string, TaskCenterEntry> = {};
    for (let index = 0; index < 25; index += 1) {
      tasks[`t${index}`] = entry({ id: `t${index}`, startedAt: index });
    }
    const reports = toPetTaskReports(tasks);
    expect(reports).toHaveLength(20);
    expect(reports[0].id).toBe('t24');
  });
});
