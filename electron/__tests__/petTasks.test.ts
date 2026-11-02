import { describe, expect, it } from 'vitest';

import { applyTaskOverrides, normalizeTaskReports } from '../pet/tasks';
import type { PetSnapshot, PetTaskReport } from '../pet/types';

const NOW = 1_700_000_000_000;

function snapshot(overrides: Partial<PetSnapshot> = {}): PetSnapshot {
  return {
    action: 'idle',
    detail: null,
    sessionId: null,
    sessionTitle: null,
    toolName: null,
    bubbleKey: null,
    bubbleKind: null,
    todoDone: 0,
    todoTotal: 0,
    todoActive: null,
    progressKind: null,
    contextUsed: null,
    contextMax: null,
    lastTerminalAction: null,
    lastTerminalAt: null,
    patCount: 0,
    bondDays: 1,
    activeSessions: 0,
    sessions: [],
    tasks: [],
    updatedAt: NOW,
    ...overrides,
  };
}

function task(overrides: Partial<PetTaskReport> = {}): PetTaskReport {
  return {
    id: 't1',
    kind: 'office',
    title: '生成周报',
    status: 'running',
    startedAt: NOW - 1000,
    ...overrides,
  };
}

describe('pet background tasks', () => {
  it('sanitizes, deduplicates and caps task reports', () => {
    const reports = normalizeTaskReports([
      { id: 'a', title: 'A', status: 'running', kind: 'office', percent: 140 },
      { id: 'a', title: 'A2', status: 'running' },
      { id: '', title: 'bad', status: 'running' },
      { id: 'b', title: 'B', status: 'nope' },
      { id: 'c', title: 'C', status: 'awaiting_approval', percent: 12.6 },
    ]);
    expect(reports).toHaveLength(2);
    expect(reports[0]).toMatchObject({ id: 'a', percent: 100, kind: 'office' });
    expect(reports[1]).toMatchObject({ id: 'c', percent: 13, status: 'awaiting_approval' });
  });

  it('shows the most urgent background task when the pet is idle', () => {
    const tasks = [
      task({ id: 'run', status: 'running' }),
      task({ id: 'wait', status: 'awaiting_approval', title: '等审批' }),
      task({ id: 'fail', status: 'failed', finishedAt: NOW - 1000 }),
    ];
    const result = applyTaskOverrides(snapshot(), tasks, NOW);
    expect(result.action).toBe('waiting');
    expect(result.sessionTitle).toBe('等审批');
    expect(result.toolName).toBe('后台任务');
  });

  it('does not mask an active chat session', () => {
    const result = applyTaskOverrides(
      snapshot({ action: 'thinking', sessionId: 's1' }),
      [task({ status: 'awaiting_approval' })],
      NOW,
    );
    expect(result.action).toBe('thinking');
    expect(result.sessionId).toBe('s1');
  });

  it('ignores failures outside the display window', () => {
    const result = applyTaskOverrides(
      snapshot(),
      [task({ status: 'failed', finishedAt: NOW - 11 * 60_000 })],
      NOW,
    );
    expect(result.action).toBe('idle');
  });
});
