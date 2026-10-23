import { describe, expect, it } from 'vitest';

import { auditTaskCenterStoreGovernance } from '../taskCenterStore';

describe('auditTaskCenterStoreGovernance (P169)', () => {
  it('returns compliant governance audit metadata for taskCenterStore', () => {
    const report = auditTaskCenterStoreGovernance();
    expect(report.module).toBe('src/features/task-center/taskCenterStore.ts');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('task-center');
    expect(report.supportsClearFinished).toBe(true);
    expect(report.tracksDeliveryAndHighlight).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
