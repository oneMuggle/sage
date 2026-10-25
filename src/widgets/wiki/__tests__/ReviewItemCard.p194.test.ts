import { describe, expect, it } from 'vitest';

import { auditReviewItemCardGovernance } from '../ReviewItemCard';

describe('auditReviewItemCardGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditReviewItemCardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('wiki-review-item-card');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
