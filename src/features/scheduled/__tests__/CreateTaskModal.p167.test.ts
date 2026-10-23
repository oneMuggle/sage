import { describe, expect, it } from 'vitest';

import { auditCreateTaskModalGovernance } from '../CreateTaskModal';

describe('auditCreateTaskModalGovernance (P167)', () => {
  it('returns compliant governance audit metadata for CreateTaskModal', () => {
    const report = auditCreateTaskModalGovernance();
    expect(report.module).toBe('src/features/scheduled/CreateTaskModal.tsx');
    expect(report.phase).toBe('P167');
    expect(report.domain).toBe('scheduled');
    expect(report.validatesSkillRefs).toBe(true);
    expect(report.supportsCronPicker).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
