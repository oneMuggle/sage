// src/shared/__tests__/logger.test.ts
import { describe, expect, it } from 'vitest';

import { createLogger } from '../logger';
import { formatLoggerEntryJson, formatLoggerEntrySummary } from '../logger';

describe('createLogger', () => {
  it('returns object with 4 methods', () => {
    const logger = createLogger('test');
    expect(logger).toHaveProperty('debug');
    expect(logger).toHaveProperty('info');
    expect(logger).toHaveProperty('warn');
    expect(logger).toHaveProperty('error');
  });

  it('logger methods are functions', () => {
    const logger = createLogger('test');
    expect(typeof logger.debug).toBe('function');
    expect(typeof logger.info).toBe('function');
  });

  it('formats logger entry summary and JSON (Phase P112)', () => {
    expect(formatLoggerEntrySummary('ipc', 'warn', 'slow call')).toBe('[ipc] WARN · slow call');
    expect(JSON.parse(formatLoggerEntryJson('ipc', 'warn', 'slow call'))).toEqual({
      scope: 'ipc',
      level: 'warn',
      message: 'slow call',
    });
  });
});
