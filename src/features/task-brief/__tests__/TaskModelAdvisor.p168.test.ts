import { describe, expect, it } from 'vitest';

import { auditTaskModelAdvisorGovernance } from '../TaskModelAdvisor';

describe('auditTaskModelAdvisorGovernance (P168)', () => {
  it('returns compliant governance audit metadata for TaskModelAdvisor', () => {
    const report = auditTaskModelAdvisorGovernance();
    expect(report.module).toBe('src/features/task-brief/TaskModelAdvisor.tsx');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('task-brief');
    expect(report.linksToModelCatalogAndSettings).toBe(true);
    expect(report.gracefullyHandlesMissingMetadata).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
