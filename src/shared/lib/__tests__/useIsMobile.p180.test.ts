import { describe, expect, it } from 'vitest';

import {
  auditUseIsMobileGovernance,
  formatViewportMobileJson,
  formatViewportMobileSummary,
  MOBILE_BREAKPOINT_PX,
} from '../useIsMobile';

describe('useIsMobile P180 governance audit', () => {
  it('audits useIsMobile governance contract and viewport helpers', () => {
    const raw = auditUseIsMobileGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.use_is_mobile.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.breakpointPx).toBe(MOBILE_BREAKPOINT_PX);
    expect(formatViewportMobileSummary(600)).toContain('mobile=true');
    expect(JSON.parse(formatViewportMobileJson(1024)).isMobile).toBe(false);
  });
});
