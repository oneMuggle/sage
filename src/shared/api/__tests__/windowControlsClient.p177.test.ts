import { describe, expect, it } from 'vitest';

import {
  auditWindowControlsClientGovernance,
  detectPlatform,
  formatWindowPlatformJson,
  formatWindowPlatformSummary,
  isElectronDesktop,
} from '../windowControlsClient';

describe('windowControlsClient P177 governance audit', () => {
  it('audits windowControlsClient governance contract and platform helpers', () => {
    const raw = auditWindowControlsClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.window_controls_client.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.supportedPlatforms).toContain('windows');
    expect(detectPlatform('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('windows');
    expect(isElectronDesktop('windows')).toBe(true);
    expect(formatWindowPlatformSummary('windows', true)).toBe('windows · desktop · ipc-bridge');
    expect(JSON.parse(formatWindowPlatformJson('web', false)).isDesktop).toBe(false);
  });
});
