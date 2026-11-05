import { describe, expect, it } from 'vitest';

import {
  computeAttention,
  liveSessionIds,
  nextInCycle,
  resolveFollowTarget,
} from '../pet/attention';
import type { SessionPetState } from '../pet/state';

const T0 = 1_000_000;

function session(overrides: Partial<SessionPetState> = {}): SessionPetState {
  return {
    action: 'idle',
    detail: null,
    toolName: null,
    bubbleKey: null,
    bubbleKind: null,
    priority: 0,
    updatedAt: T0,
    terminalAt: null,
    sessionTitle: null,
    todoDone: 0,
    todoTotal: 0,
    todoActive: null,
    progressKind: null,
    contextUsed: null,
    contextMax: null,
    lastTerminalAction: null,
    lastTerminalAt: null,
    ...overrides,
  };
}

describe('computeAttention', () => {
  it('counts sessions and task approvals without truncation', () => {
    const sessions = {
      a: session({ action: 'acting' }),
      b: session({ action: 'waiting', updatedAt: T0 + 2 }),
      c: session({ action: 'error' }),
      d: session({ action: 'thinking' }),
      e: session({ action: 'done' }),
    };
    const tasks = [
      { id: 't1', kind: 'orchestration', title: '审批', status: 'awaiting_approval' as const },
      { id: 't2', kind: 'scheduled', title: '运行', status: 'running' as const },
      { id: 't3', kind: 'scheduled', title: '失败', status: 'failed' as const, finishedAt: T0 },
      {
        id: 't4',
        kind: 'scheduled',
        title: '旧失败',
        status: 'failed' as const,
        finishedAt: T0 - 11 * 60_000,
      },
    ];
    expect(computeAttention(sessions, tasks, T0)).toEqual({
      needsYou: 2,
      failed: 2,
      running: 2,
      activeTasks: 2,
      total: 8,
      needsYouSessionIds: ['b'],
    });
  });

  it('sorts needs-you sessions by recency and caps the id list at 20', () => {
    const sessions: Record<string, SessionPetState> = {};
    for (let i = 0; i < 25; i++) {
      sessions[`s${i}`] = session({ action: 'waiting', updatedAt: T0 + i });
    }
    expect(computeAttention(sessions, [], T0).needsYouSessionIds).toHaveLength(20);
    expect(computeAttention(sessions, [], T0).needsYouSessionIds[0]).toBe('s24');
    expect(computeAttention({}, [], T0)).toEqual({
      needsYou: 0,
      failed: 0,
      running: 0,
      activeTasks: 0,
      total: 0,
      needsYouSessionIds: [],
    });
  });
});

describe('resolveFollowTarget', () => {
  const sessions = {
    a: session({ action: 'acting', updatedAt: T0 + 3 }),
    b: session({ action: 'waiting', updatedAt: T0 + 2 }),
    c: session({ action: 'idle', updatedAt: T0 + 1 }),
  };

  it('follows the focused session while it is live', () => {
    expect(
      resolveFollowTarget(sessions, {
        mode: 'focus',
        focusSessionId: 'a',
        pinnedSessionId: null,
      }),
    ).toBe('a');
  });

  it('falls back to the highest-priority live session when focus is idle', () => {
    expect(
      resolveFollowTarget(sessions, {
        mode: 'focus',
        focusSessionId: 'c',
        pinnedSessionId: null,
      }),
    ).toBe('b');
  });

  it('keeps the focused session when everything is idle', () => {
    expect(
      resolveFollowTarget(
        { c: sessions.c },
        { mode: 'focus', focusSessionId: 'c', pinnedSessionId: null },
      ),
    ).toBe('c');
  });

  it('pinned wins even when the pinned session is idle', () => {
    expect(
      resolveFollowTarget(sessions, {
        mode: 'pinned',
        focusSessionId: 'a',
        pinnedSessionId: 'c',
      }),
    ).toBe('c');
  });

  it('falls back when the pinned session disappeared', () => {
    expect(
      resolveFollowTarget(sessions, {
        mode: 'pinned',
        focusSessionId: 'a',
        pinnedSessionId: 'gone',
      }),
    ).toBe('a');
  });

  it('urgent picks waiting over acting and returns null with no sessions', () => {
    expect(
      resolveFollowTarget(sessions, {
        mode: 'urgent',
        focusSessionId: 'a',
        pinnedSessionId: null,
      }),
    ).toBe('b');
    expect(
      resolveFollowTarget({}, { mode: 'urgent', focusSessionId: null, pinnedSessionId: null }),
    ).toBeNull();
  });
});

describe('cycle helpers', () => {
  it('orders live sessions by priority and wraps around', () => {
    const ids = liveSessionIds({
      a: session({ action: 'acting' }),
      b: session({ action: 'waiting' }),
      c: session({ action: 'thinking' }),
      d: session({ action: 'done' }),
    });
    expect(ids).toEqual(['b', 'a', 'c']);
    expect(nextInCycle(ids, 'c')).toBe('b');
    expect(nextInCycle(ids, null)).toBe('b');
    expect(nextInCycle([], 'b')).toBeNull();
  });
});
