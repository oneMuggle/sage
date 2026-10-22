import { describe, expect, it } from 'vitest';

import { evaluateVirtualSessionListGovernanceAudit } from '../VirtualSessionList';

describe('evaluateVirtualSessionListGovernanceAudit (Phase P139)', () => {
  it('returns healthy report for properly virtualized session list metrics', () => {
    const report = evaluateVirtualSessionListGovernanceAudit({
      totalSessionCount: 200,
      renderedRowCount: 16,
      rowHeightPx: 44,
      overscanCount: 5,
    });
    expect(report.healthy).toBe(true);
    expect(report.virtualizationRatio).toBe(0.08);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags invalid row height, out-of-range overscan, and render overflow', () => {
    const report = evaluateVirtualSessionListGovernanceAudit({
      totalSessionCount: 10,
      renderedRowCount: 40,
      rowHeightPx: 8,
      overscanCount: 80,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'VIRTUAL_SESSION_LIST_ROW_HEIGHT_INVALID',
      'VIRTUAL_SESSION_LIST_OVERSCAN_OUT_OF_RANGE',
    ]);
  });
});
