import { describe, expect, it } from 'vitest';

import { evaluateBackendStatusBannerGovernanceAudit } from '../BackendStatusBanner';

describe('evaluateBackendStatusBannerGovernanceAudit (Phase P139)', () => {
  it('returns healthy report when backend status is ok or recovering within valid timeout', () => {
    const report = evaluateBackendStatusBannerGovernanceAudit({
      bannerState: 'ok',
      reconnectAttempt: 0,
      recoveredVisibleMs: 2000,
    });
    expect(report.healthy).toBe(true);
    expect(report.isBannerVisible).toBe(false);
    expect(report.requiresAppRestart).toBe(false);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags auth_failed state and out-of-range recovery timeout', () => {
    const report = evaluateBackendStatusBannerGovernanceAudit({
      bannerState: 'auth_failed',
      reconnectAttempt: 0,
      recoveredVisibleMs: 100,
    });
    expect(report.healthy).toBe(false);
    expect(report.isBannerVisible).toBe(true);
    expect(report.requiresAppRestart).toBe(true);
    expect(report.issueCodes).toEqual([
      'BACKEND_BANNER_AUTH_FAILED',
      'BACKEND_BANNER_RECOVER_TIMEOUT_OUT_OF_RANGE',
    ]);
  });
});
