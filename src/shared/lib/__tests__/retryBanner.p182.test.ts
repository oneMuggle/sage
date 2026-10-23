import { describe, expect, it } from 'vitest';

import { auditRetryBannerGovernance } from '../i18n/retryBanner';

describe('auditRetryBannerGovernance (Phase P182)', () => {
  it('returns deterministic P182 governance audit payload', () => {
    const payload = JSON.parse(auditRetryBannerGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('retry-banner');
    expect(payload.phase).toBe('P182');
    expect(payload.audited).toBe(true);
  });
});
