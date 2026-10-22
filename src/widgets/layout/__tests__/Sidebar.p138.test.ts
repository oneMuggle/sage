import { describe, expect, it } from 'vitest';

import { evaluateSidebarGovernanceAudit } from '../Sidebar';

describe('evaluateSidebarGovernanceAudit (Phase P138)', () => {
  it('returns healthy report for valid sidebar counts and width', () => {
    const report = evaluateSidebarGovernanceAudit({
      sessionCount: 14,
      projectCount: 4,
      widthPx: 300,
      collapsed: false,
    });
    expect(report.healthy).toBe(true);
    expect(report.effectiveWidthPx).toBe(300);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags negative counts and out-of-range expanded width', () => {
    const report = evaluateSidebarGovernanceAudit({
      sessionCount: -1,
      projectCount: -2,
      widthPx: 90,
      collapsed: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'SIDEBAR_SESSION_COUNT_NEGATIVE',
      'SIDEBAR_PROJECT_COUNT_NEGATIVE',
      'SIDEBAR_WIDTH_OUT_OF_RANGE',
    ]);
  });
});
