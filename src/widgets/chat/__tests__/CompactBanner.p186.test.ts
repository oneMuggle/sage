import { describe, expect, it } from 'vitest';

import { auditCompactBannerGovernance } from '../CompactBanner';

describe('auditCompactBannerGovernance (Phase P186)', () => {
  it('returns deterministic P186 governance audit payload', () => {
    const payload = JSON.parse(auditCompactBannerGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('compact-banner');
    expect(payload.phase).toBe('P186');
    expect(payload.audited).toBe(true);
  });
});
