import { describe, expect, it } from 'vitest';

import { evaluateLayoutShellGovernanceAudit } from '../Layout';

describe('evaluateLayoutShellGovernanceAudit (Phase P138)', () => {
  it('returns healthy report for standard layout dimensions with visible main content', () => {
    const report = evaluateLayoutShellGovernanceAudit({
      sidebarWidthPx: 280,
      sidebarCollapsed: false,
      viewportWidthPx: 1280,
      mainContentVisible: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.effectiveSidebarWidthPx).toBe(280);
    expect(report.remainingContentWidthPx).toBe(1000);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags out-of-bounds sidebar width, cramped main content, and hidden main content', () => {
    const report = evaluateLayoutShellGovernanceAudit({
      sidebarWidthPx: 620,
      sidebarCollapsed: false,
      viewportWidthPx: 700,
      mainContentVisible: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'LAYOUT_SIDEBAR_WIDTH_OUT_OF_BOUNDS',
      'LAYOUT_MAIN_CONTENT_CRAMPED',
      'LAYOUT_MAIN_CONTENT_HIDDEN',
    ]);
  });
});
