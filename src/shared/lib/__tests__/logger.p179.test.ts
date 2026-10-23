import { describe, expect, it } from 'vitest';

import {
  auditLoggerGovernance,
  formatLoggerAuditJson,
  formatLoggerAuditSummary,
} from '../logger';

describe('logger P179 governance audit', () => {
  it('audits logger governance contract and logger audit formatters', () => {
    const raw = auditLoggerGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.logger.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.levels).toEqual(['debug', 'info', 'warn', 'error']);
    expect(formatLoggerAuditSummary(false)).toBe('logger=disabled');
    expect(JSON.parse(formatLoggerAuditJson(true)).enabled).toBe(true);
  });
});
