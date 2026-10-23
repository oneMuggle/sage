import { describe, expect, it } from 'vitest';

import { auditLoggerGovernance } from '../logger';

describe('auditLoggerGovernance (P174)', () => {
  it('returns compliant governance audit metadata for logger', () => {
    const report = auditLoggerGovernance();
    expect(report.module).toBe('src/shared/logger.ts');
    expect(report.phase).toBe('P174');
    expect(report.domain).toBe('shared');
    expect(report.levels).toEqual(['debug', 'info', 'warn', 'error']);
    expect(report.compliant).toBe(true);
  });
});
