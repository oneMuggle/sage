import { describe, expect, it } from 'vitest';

import { auditScheduledTasksPageGovernance } from '../ScheduledTasks';

describe('auditScheduledTasksPageGovernance (P171)', () => {
  it('returns compliant governance audit metadata for ScheduledTasks page', () => {
    const report = auditScheduledTasksPageGovernance();
    expect(report.module).toBe('src/pages/ScheduledTasks.tsx');
    expect(report.phase).toBe('P171');
    expect(report.domain).toBe('pages');
    expect(report.supportsRunNowToggleAndEdit).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
