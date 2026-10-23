import { describe, expect, it } from 'vitest';

import { auditGitStatusApiGovernance } from '../gitStatusApi';

describe('auditGitStatusApiGovernance (P175)', () => {
  it('returns compliant governance audit metadata for gitStatusApi', () => {
    const report = auditGitStatusApiGovernance();
    expect(report.module).toBe('src/shared/api/gitStatusApi.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.fileChangeStatuses).toHaveLength(6);
    expect(report.compliant).toBe(true);
  });
});
