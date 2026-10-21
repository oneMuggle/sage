import { describe, expect, it } from 'vitest';

import {
  logger,
  formatLoggerAuditSummary,
  formatLoggerAuditJson,
} from '../logger';

describe('logger audit helpers', () => {
  it('toggles logger and formats audit summary and json', () => {
    logger.setEnabled(false);
    expect(logger.isEnabled()).toBe(false);
    expect(formatLoggerAuditSummary()).toBe('logger=disabled');
    expect(formatLoggerAuditSummary(true)).toBe('logger=enabled');
    expect(JSON.parse(formatLoggerAuditJson(true))).toEqual({
      enabled: true,
    });
  });

  it('falls back to logger instance state when nullish', () => {
    logger.setEnabled(true);
    expect(formatLoggerAuditSummary(null)).toBe('logger=enabled');
    expect(JSON.parse(formatLoggerAuditJson(undefined)).enabled).toBe(true);
  });
});
