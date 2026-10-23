import { describe, expect, it } from 'vitest';

import {
  auditUseResizablePanelGovernance,
  formatResizablePanelJson,
  formatResizablePanelSummary,
} from '../useResizablePanel';

describe('useResizablePanel P180 governance audit', () => {
  it('audits useResizablePanel governance contract and width clamp formatters', () => {
    const raw = auditUseResizablePanelGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.use_resizable_panel.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.sampleSummary).toContain('width=360px');
    expect(formatResizablePanelSummary(100, 240, 640)).toContain('width=240px');
    expect(JSON.parse(formatResizablePanelJson(800, 240, 640)).width).toBe(640);
  });
});
