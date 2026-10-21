import { describe, expect, it } from 'vitest';

import {
  DEFAULT_SETTINGS,
  formatSettingsAuditJson,
  formatSettingsAuditSummary,
  withDemoSettingsDefaults,
} from '../types';

describe('setting types audit helpers', () => {
  it('formats settings audit summary and applies demo defaults', () => {
    const demo = withDemoSettingsDefaults(DEFAULT_SETTINGS);
    expect(demo.demoMode).toBe(true);
    expect(formatSettingsAuditSummary(demo)).toContain('demo=true');
  });

  it('serializes settings audit JSON', () => {
    const parsed = JSON.parse(
      formatSettingsAuditJson({
        version: '5.0',
        endpoints: [],
        demoMode: false,
        timezone: 'Asia/Shanghai',
      }),
    );
    expect(parsed).toEqual({
      version: '5.0',
      endpointCount: 0,
      demoMode: false,
      timezone: 'Asia/Shanghai',
    });
  });
});
