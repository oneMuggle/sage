import { describe, expect, it } from 'vitest';

import {
  getDemoModeOverride,
  setDemoModeOverride,
  formatDemoRuntimeSummary,
  formatDemoRuntimeJson,
} from '../demoRuntime';

describe('demoRuntime audit helpers', () => {
  it('formats demo runtime override summary and json', () => {
    setDemoModeOverride(true);
    expect(getDemoModeOverride()).toBe(true);
    expect(formatDemoRuntimeSummary()).toBe('demoOverride=true');
    const parsed = JSON.parse(formatDemoRuntimeJson(false));
    expect(parsed).toEqual({
      demoOverride: false,
      configured: true,
    });
  });

  it('handles unset or nullish override safely', () => {
    expect(formatDemoRuntimeSummary(null)).toBe('demoOverride=unset');
    expect(JSON.parse(formatDemoRuntimeJson(null)).configured).toBe(false);
  });
});
