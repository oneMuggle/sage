import { describe, expect, it } from 'vitest';

import { auditRetryBannerGovernance } from '../RetryBanner';

describe('auditRetryBannerGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditRetryBannerGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('retry-banner');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
