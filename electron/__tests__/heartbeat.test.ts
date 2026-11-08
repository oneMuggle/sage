/**
 * heartbeat — renderer 心跳超时纯逻辑（不依赖 Electron）。
 */
import { describe, expect, it } from 'vitest';

import { createHeartbeatMonitor } from '../heartbeat';

describe('createHeartbeatMonitor', () => {
  it('reports not lost before timeout', () => {
    const m = createHeartbeatMonitor({ timeoutMs: 60_000 });
    m.beat(1000);
    expect(m.check(30_000)).toBe(false);
  });

  it('reports lost after timeout', () => {
    const m = createHeartbeatMonitor({ timeoutMs: 60_000 });
    m.beat(1000);
    expect(m.check(62_000)).toBe(true);
  });

  it('fires at most once until reset', () => {
    const m = createHeartbeatMonitor({ timeoutMs: 60_000 });
    m.beat(1000);
    expect(m.check(62_000)).toBe(true);
    expect(m.check(120_000)).toBe(false);
  });

  it('beat after lost re-arms', () => {
    const m = createHeartbeatMonitor({ timeoutMs: 60_000 });
    m.beat(1000);
    expect(m.check(62_000)).toBe(true);
    m.beat(63_000);
    expect(m.check(64_000)).toBe(false);
  });

  it('starts in lost state until first beat', () => {
    const m = createHeartbeatMonitor({ timeoutMs: 60_000 });
    expect(m.check(1000)).toBe(false);
  });
});
