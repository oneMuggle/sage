import { describe, expect, it } from 'vitest';

import {
  auditOfficeProgressGovernance,
  formatOfficeProgressJson,
  formatOfficeProgressSummary,
} from '../officeProgress';

describe('officeProgress governance audit (P165)', () => {
  it('returns ready governance status for officeProgress', () => {
    const snap = auditOfficeProgressGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/officeProgress.ts',
      phase: 'P165',
      status: 'ready',
    });
  });

  it('formats office progress summary and json', () => {
    expect(formatOfficeProgressSummary('t1', { stage: 'export', percent: 50 })).toContain(
      'task=t1 · stage=export · percent=50%',
    );
    expect(JSON.parse(formatOfficeProgressJson('t1', { stage: 'export', percent: 50 }))).toEqual({
      taskId: 't1',
      stage: 'export',
      percent: 50,
    });
  });
});
