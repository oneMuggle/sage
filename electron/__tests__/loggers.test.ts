// electron/__tests__/loggers.test.ts
import { describe, expect, it } from 'vitest';

import { createLogger } from '../loggers';

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
});
