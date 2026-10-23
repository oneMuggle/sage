import { describe, expect, it } from 'vitest';

import { auditModelTaskFitGovernance } from '../modelTaskFit';

describe('auditModelTaskFitGovernance (P168)', () => {
  it('returns compliant governance audit metadata for modelTaskFit', () => {
    const report = auditModelTaskFitGovernance();
    expect(report.module).toBe('src/features/task-brief/modelTaskFit.ts');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('task-brief');
    expect(report.evaluatesToolCallingAndPricing).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
