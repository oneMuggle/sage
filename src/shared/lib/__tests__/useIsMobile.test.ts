import { describe, expect, it } from 'vitest';

import {
  MOBILE_BREAKPOINT_PX,
  formatViewportMobileSummary,
  formatViewportMobileJson,
} from '../useIsMobile';

describe('useIsMobile audit helpers', () => {
  it('formats mobile viewport summary and json', () => {
    expect(formatViewportMobileSummary(375)).toBe(
      `viewport=375px · mobile=true · breakpoint=${MOBILE_BREAKPOINT_PX}px`,
    );
    const parsed = JSON.parse(formatViewportMobileJson(1280));
    expect(parsed).toEqual({
      viewportWidth: 1280,
      isMobile: false,
      breakpointPx: MOBILE_BREAKPOINT_PX,
    });
  });

  it('handles explicit override and nullish inputs safely', () => {
    expect(formatViewportMobileSummary(null, false)).toContain('mobile=false');
    expect(JSON.parse(formatViewportMobileJson(600, true)).isMobile).toBe(true);
  });
});
