import { describe, expect, it } from 'vitest';

import { compareSessions, isSessionActive, sortSessions } from '../sessionOrder';
import type { Session } from '../store';

function makeSession(overrides: Partial<Session> & { id: string }): Session {
  return {
    title: overrides.id,
    created_at: 0,
    updated_at: 0,
    last_message_at: null,
    message_count: 0,
    is_pinned: false,
    ...overrides,
  };
}

describe('compareSessions（与后端 SQL 排序一致）', () => {
  it('pinned 永远在最前，即使 updated_at 更旧', () => {
    const pinned = makeSession({ id: 'pinned', is_pinned: true, updated_at: 1 });
    const fresh = makeSession({ id: 'fresh', updated_at: 9_999 });
    expect(sortSessions([fresh, pinned]).map((s) => s.id)).toEqual(['pinned', 'fresh']);
  });

  it('非 pinned 中 running/suspended 排在 idle 之前', () => {
    const running = makeSession({ id: 'running', run_status: 'running', updated_at: 1 });
    const suspended = makeSession({ id: 'suspended', run_status: 'suspended', updated_at: 2 });
    const idle = makeSession({ id: 'idle', run_status: 'idle', updated_at: 9_999 });
    const unknown = makeSession({ id: 'unknown', updated_at: 8_888 });
    expect(sortSessions([idle, unknown, running, suspended]).map((s) => s.id)).toEqual([
      'suspended',
      'running',
      'idle',
      'unknown',
    ]);
  });

  it('同组内按 updated_at DESC', () => {
    const older = makeSession({ id: 'older', updated_at: 1 });
    const newer = makeSession({ id: 'newer', updated_at: 2 });
    expect(compareSessions(newer, older)).toBeLessThan(0);
    expect(compareSessions(older, newer)).toBeGreaterThan(0);
  });

  it('isSessionActive 只认 running/suspended', () => {
    expect(isSessionActive({ run_status: 'running' })).toBe(true);
    expect(isSessionActive({ run_status: 'suspended' })).toBe(true);
    expect(isSessionActive({ run_status: 'failed' })).toBe(false);
    expect(isSessionActive({})).toBe(false);
  });

  it('sortSessions 不修改入参数组', () => {
    const a = makeSession({ id: 'a', updated_at: 1 });
    const b = makeSession({ id: 'b', updated_at: 2 });
    const input = [a, b];
    sortSessions(input);
    expect(input.map((s) => s.id)).toEqual(['a', 'b']);
  });
});
