// electron/__tests__/loggers.test.ts
import { createLogger } from '../loggers';

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
