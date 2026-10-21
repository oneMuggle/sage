import { describe, expect, it } from 'vitest';

import {
  DEFAULT_LOG_LEVEL,
  RATE_LIMIT_WARN_INTERVAL_MS,
  formatLogLevelSummary,
  formatLogLevelJson,
} from '../levels';

describe('shared/log/levels audit helpers', () => {
  it('formats log level summary and json', () => {
    expect(formatLogLevelSummary('warn')).toBe(
      `level=warn · rank=2 · rateLimitMs=${RATE_LIMIT_WARN_INTERVAL_MS}`,
    );
    const parsed = JSON.parse(formatLogLevelJson('error'));
    expect(parsed).toEqual({
      level: 'error',
      rank: 3,
      defaultLevel: DEFAULT_LOG_LEVEL,
      rateLimitWarnIntervalMs: RATE_LIMIT_WARN_INTERVAL_MS,
    });
  });

  it('falls back to default log level when nullish', () => {
    expect(formatLogLevelSummary(null)).toBe(
      `level=${DEFAULT_LOG_LEVEL} · rank=1 · rateLimitMs=${RATE_LIMIT_WARN_INTERVAL_MS}`,
    );
    expect(JSON.parse(formatLogLevelJson(undefined)).level).toBe(DEFAULT_LOG_LEVEL);
  });
});
