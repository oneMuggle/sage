import { describe, expect, it } from 'vitest';

import { evaluateResizeDividerGovernanceAudit } from '../ResizeDivider';

describe('evaluateResizeDividerGovernanceAudit (Phase P138)', () => {
  it('returns healthy report when proposed width is within valid resize bounds', () => {
    const report = evaluateResizeDividerGovernanceAudit({
      minWidthPx: 200,
      maxWidthPx: 450,
      proposedWidthPx: 300,
      isDragging: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.clampedWidthPx).toBe(300);
    expect(report.withinBounds).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags invalid bounds and out-of-range proposed width', () => {
    const report = evaluateResizeDividerGovernanceAudit({
      minWidthPx: 400,
      maxWidthPx: 300,
      proposedWidthPx: 520,
      isDragging: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'RESIZE_DIVIDER_BOUNDS_INVALID',
      'RESIZE_DIVIDER_WIDTH_CLAMPED',
    ]);
  });
});
