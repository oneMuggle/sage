import { describe, expect, it } from 'vitest';

import { __test__sanitizeForBackend } from '../storage';
import { DEFAULT_FAILOVER_SETTINGS, DEFAULT_SETTINGS } from '../types';

describe('failover settings (2026-11-26)', () => {
  it('defaults failover to disabled with sane intervals', () => {
    expect(DEFAULT_FAILOVER_SETTINGS.enabled).toBe(false);
    expect(DEFAULT_FAILOVER_SETTINGS.probeIntervalMs).toBe(300_000);
    expect(DEFAULT_FAILOVER_SETTINGS.cooldownMs).toBe(60_000);
    expect(DEFAULT_FAILOVER_SETTINGS.consecutiveFailThreshold).toBe(2);
    expect(DEFAULT_SETTINGS.failover).toEqual(DEFAULT_FAILOVER_SETTINGS);
  });

  it('sanitizeForBackend keeps failover and endpoint priority', () => {
    const sanitized = __test__sanitizeForBackend({
      failover: {
        enabled: true,
        probeIntervalMs: 120_000,
        cooldownMs: 30_000,
        consecutiveFailThreshold: 3,
      },
      endpoints: [
        {
          id: 'ep1',
          name: 'primary',
          baseUrl: 'http://localhost:1234/v1',
          apiKey: 'k',
          protocol: 'openai-compatible',
          modelId: '',
          localModelPath: '',
          discoveredModels: [],
          lastDiscoveredAt: null,
          reasoningEffort: null,
          thinkingBudget: null,
          priority: 1,
        },
      ],
    });
    expect(sanitized.failover).toEqual({
      enabled: true,
      probeIntervalMs: 120_000,
      cooldownMs: 30_000,
      consecutiveFailThreshold: 3,
    });
    expect(sanitized.endpoints?.[0]?.priority).toBe(1);
  });
});
