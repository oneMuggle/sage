import { describe, expect, it } from 'vitest';

import { DEFAULT_PET_CONFIG } from '../pet/config';
import { buildStatusPayload } from '../pet/statusPayload';
import type { PetSnapshot } from '../pet/types';

const NOW = 1_700_000_000_000;

function snapshot(overrides: Partial<PetSnapshot> = {}): PetSnapshot {
  return {
    action: 'acting',
    detail: 'edit',
    sessionId: 'session-1',
    sessionTitle: '写周报',
    toolName: 'write_file',
    bubbleKey: 'tool_edit',
    bubbleKind: 'info',
    todoDone: 2,
    todoTotal: 5,
    todoActive: '写测试',
    progressKind: 'todo',
    contextUsed: 40_000,
    contextMax: 128_000,
    lastTerminalAction: 'done',
    lastTerminalAt: NOW - 1_000,
    patCount: 3,
    bondDays: 2,
    activeSessions: 1,
    sessions: Array.from({ length: 7 }, (_, index) => ({
      sessionId: `session-${index}`,
      sessionTitle: `会话 ${index}`,
      action: 'thinking' as const,
      detail: null,
      toolName: null,
      bubbleKey: null,
      todoDone: index,
      todoTotal: 5,
      todoActive: null,
      progressKind: null,
      contextUsed: null,
      contextMax: null,
      lastTerminalAction: null,
      lastTerminalAt: null,
      updatedAt: NOW + index,
    })),
    tasks: Array.from({ length: 12 }, (_, index) => ({
      id: `task-${index}`,
      kind: 'office',
      title: `任务 ${index}`,
      status: 'running' as const,
      phase: null,
      percent: index,
      sessionId: `session-${index}`,
      runId: null,
      error: `/secret/path/${index}`,
      startedAt: NOW,
      finishedAt: null,
    })),
    updatedAt: NOW,
    ...overrides,
  };
}

describe('buildStatusPayload', () => {
  it('mirrors the panel state and caps list sizes', () => {
    const payload = buildStatusPayload(snapshot(), {
      ...DEFAULT_PET_CONFIG,
      externalApi: true,
    });
    expect(payload).toMatchObject({
      version: 1,
      updatedAt: NOW,
      action: 'acting',
      detail: 'edit',
      sessionId: 'session-1',
      sessionTitle: '写周报',
      toolName: 'write_file',
      todo: { done: 2, total: 5, active: '写测试' },
      progressKind: 'todo',
      context: { used: 40_000, max: 128_000 },
      lastTerminal: { action: 'done', at: NOW - 1_000 },
      companion: { bondDays: 2, patCount: 3 },
      activeSessions: 1,
    });
    expect(payload.sessions).toHaveLength(5);
    expect(payload.tasks).toHaveLength(10);
    expect(payload.pets).toEqual([{ id: 'default', petPack: 'dafeiyu', size: 'medium' }]);
    expect(payload.config).toMatchObject({ externalApi: true, displayMode: 'desktop' });
  });

  it('never exposes task error strings', () => {
    const payload = buildStatusPayload(snapshot(), DEFAULT_PET_CONFIG);
    for (const task of payload.tasks) {
      expect(task).not.toHaveProperty('error');
    }
    expect(JSON.stringify(payload)).not.toContain('/secret/path');
  });

  it('maps a missing terminal state to null', () => {
    const payload = buildStatusPayload(
      snapshot({ lastTerminalAction: null, lastTerminalAt: null }),
      DEFAULT_PET_CONFIG,
    );
    expect(payload.lastTerminal).toBeNull();
  });
});
