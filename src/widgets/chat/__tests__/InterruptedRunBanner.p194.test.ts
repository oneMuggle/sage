import { describe, expect, it } from 'vitest';

import { auditInterruptedRunBannerGovernance } from '../InterruptedRunBanner';

describe('auditInterruptedRunBannerGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditInterruptedRunBannerGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('interrupted-run-banner');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
