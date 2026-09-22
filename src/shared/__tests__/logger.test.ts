// src/shared/__tests__/logger.test.ts
import { createLogger } from '../logger';

test('createLogger returns object with 4 methods', () => {
  const logger = createLogger('test');
  expect(logger).toHaveProperty('debug');
  expect(logger).toHaveProperty('info');
  expect(logger).toHaveProperty('warn');
  expect(logger).toHaveProperty('error');
});

test('logger methods are functions', () => {
  const logger = createLogger('test');
  expect(typeof logger.debug).toBe('function');
  expect(typeof logger.info).toBe('function');
});
