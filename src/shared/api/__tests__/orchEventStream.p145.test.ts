import { describe, expect, it } from 'vitest';

import { auditOrchEventStreamGovernance } from '../orchEventStream';

describe('orchEventStream P145 governance audit', () => {
  it('returns healthy defaults for orchEventStream governance', () => {
    const res = auditOrchEventStreamGovernance();
    expect(res.module).toBe('src/shared/api/orchEventStream.ts');
    expect(res.phase).toBe('P145');
    expect(res.reconnectDelayMs).toBe(1000);
    expect(res.maxReconnectAttempts).toBe(5);
    expect(res.supportsIpcFallback).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes reconnectDelayMs and maxReconnectAttempts', () => {
    const res = auditOrchEventStreamGovernance({
      reconnectDelayMs: 20,
      maxReconnectAttempts: 0,
      supportsIpcFallback: false,
    });
    expect(res.reconnectDelayMs).toBe(100);
    expect(res.maxReconnectAttempts).toBe(0);
    expect(res.supportsIpcFallback).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
